"""实装：报文键幂等

契约：
- 同一报文编号重复装载只保留首条命运
- 不得改坏基线默认门槛 happy path（装载→入栏/坏点→结栏汇总→贯验）。
- 页面须能读到：当前策略名、命运变化、可点的下一步。

工程形态（栏规键「幂等策略」择定）：
- 甲·切流账册（默认）：账册登记已吃进编号，同号回刷整票拒绝，账册能回看拒因，现行行数不涨。
- 乙·双写归档：同号回刷的旧报文落入只读归档，现行装载只读新编号集合，现行与归档分开可读。

硬推理约束落实：
- 查重判定与流水回执同成同败：登记/裁决与装载批次回执写在同一事务（装载侧 BEGIN IMMEDIATE）。
- 两路同号并发互斥：账册主键即互斥锁，吃进的 INSERT 撞主键即转回刷裁决，不会双成功。
- 缓冲不冒同号双行：同号回刷在入栏/坏点之前被账册挡住或引入归档，不触现行表。
"""
from __future__ import annotations
import sqlite3
from app.db import 连接

NAME = "报文键幂等"
CONTRACT = "同一报文编号重复装载只保留首条命运"
HOOKS = ("before_load", "after_load", "decide_gate", "before_close", "after_close", "extra_verify_checks")

策略_切流 = "切流账册"
策略_双写 = "双写归档"
策略集 = (策略_切流, 策略_双写)

裁决_吃进 = "吃进"
裁决_驳回 = "驳回-同号"
裁决_归档 = "归档-同号"


def describe() -> dict:
    return {
        "空桩": NAME,
        "契约": CONTRACT,
        "钩子": list(HOOKS),
        "默认启用": True,
        "实装": True,
        "形态": list(策略集),
    }


def 策略名(规: dict) -> str:
    """当前幂等策略名；栏规缺省或非法值回落切流账册。"""
    名 = str((规 or {}).get("幂等策略") or 策略_切流).strip()
    return 名 if 名 in 策略集 else 策略_切流


def 吃进或回刷(conn, ev: dict, 批次: str, 时刻: str, 策略: str) -> tuple[str, str]:
    """同号裁决入口。返回 (裁决, 拒因)，裁决 ∈ {吃进, 驳回-同号, 归档-同号}。

    须在装载的 BEGIN IMMEDIATE 事务内调用：判定与回执同成同败；
    账册主键为最终互斥，并发下另一事务已提交的同号会在这里撞主键转回刷。
    """
    编号 = str(ev["报文编号"])
    已登记 = conn.execute(
        "SELECT 1 FROM 幂等账册 WHERE 报文编号=?", (编号,)
    ).fetchone()
    已在现行 = conn.execute(
        "SELECT 1 FROM 观测报文 WHERE 报文编号=?", (编号,)
    ).fetchone()
    if 已登记 or 已在现行:
        return _回刷(conn, ev, 批次, 时刻, 策略)
    try:
        conn.execute(
            """INSERT INTO 幂等账册(报文编号,首装批次,首装时刻,最近裁决,最近时刻)
               VALUES (?,?,?,?,?)""",
            (编号, 批次, 时刻, 裁决_吃进, 时刻),
        )
    except sqlite3.IntegrityError:
        # 并发互斥兜底：另一事务已登记同号
        return _回刷(conn, ev, 批次, 时刻, 策略)
    conn.execute(
        """INSERT INTO 同号裁决(报文编号,批次编号,策略,裁决,拒因,时刻)
           VALUES (?,?,?,?,?,?)""",
        (编号, 批次, 策略, 裁决_吃进, "", 时刻),
    )
    return 裁决_吃进, ""


def _回刷(conn, ev: dict, 批次: str, 时刻: str, 策略: str) -> tuple[str, str]:
    """同号回刷：账册记拒因可回看；双写形态另把旧报文落只读归档。"""
    编号 = str(ev["报文编号"])
    裁决 = 裁决_归档 if 策略 == 策略_双写 else 裁决_驳回
    if 策略 == 策略_双写:
        拒因 = f"同号回刷：{编号} 已吃进，旧报文落只读归档，现行不涨"
    else:
        拒因 = f"同号回刷：{编号} 已吃进，整票拒绝，现行不涨"
    conn.execute(
        """INSERT INTO 幂等账册(报文编号,首装批次,首装时刻,再灌次数,最近裁决,拒因,最近时刻)
           VALUES (?,?,?,1,?,?,?)
           ON CONFLICT(报文编号) DO UPDATE SET
             再灌次数=再灌次数+1, 最近裁决=excluded.最近裁决,
             拒因=excluded.拒因, 最近时刻=excluded.最近时刻""",
        (编号, 批次, 时刻, 裁决, 拒因, 时刻),
    )
    conn.execute(
        """INSERT INTO 同号裁决(报文编号,批次编号,策略,裁决,拒因,时刻)
           VALUES (?,?,?,?,?,?)""",
        (编号, 批次, 策略, 裁决, 拒因, 时刻),
    )
    if 策略 == 策略_双写:
        conn.execute(
            """INSERT INTO 同号归档(报文编号,站点键,指标键,读数,观测时,批次编号,归档时)
               VALUES (?,?,?,?,?,?,?)""",
            (编号, str(ev["站点键"]), str(ev["指标键"]), float(ev["读数"]),
             str(ev["观测时"]), 批次, 时刻),
        )
    return 裁决, 拒因


def 记首装命运(conn, 编号: str, 命运: str) -> None:
    """首条命运（入栏/坏点）回写账册，页面可读首条命运。"""
    conn.execute(
        "UPDATE 幂等账册 SET 首装命运=? WHERE 报文编号=?", (命运, 编号)
    )


# ---- 只读查询：同号裁决接口与页面水位 ----

def 账册汇总() -> dict:
    conn = 连接()
    try:
        登记 = conn.execute("SELECT COUNT(*) AS c FROM 幂等账册").fetchone()["c"]
        驳回 = conn.execute(
            "SELECT COUNT(*) AS c FROM 同号裁决 WHERE 裁决=?", (裁决_驳回,)
        ).fetchone()["c"]
        归档 = conn.execute(
            "SELECT COUNT(*) AS c FROM 同号裁决 WHERE 裁决=?", (裁决_归档,)
        ).fetchone()["c"]
        再灌 = conn.execute(
            "SELECT COALESCE(SUM(再灌次数),0) AS c FROM 幂等账册"
        ).fetchone()["c"]
        归档行 = conn.execute("SELECT COUNT(*) AS c FROM 同号归档").fetchone()["c"]
        return {
            "登记": 登记,
            "驳回同号": 驳回,
            "归档同号": 归档,
            "再灌": int(再灌),
            "归档行数": 归档行,
        }
    finally:
        conn.close()


def 裁决列表(限制: int = 200) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 同号裁决 ORDER BY 编号 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


def 归档列表(编号: str | None = None, 限制: int = 200) -> list[dict]:
    conn = 连接()
    try:
        if 编号:
            rows = conn.execute(
                "SELECT * FROM 同号归档 WHERE 报文编号=? ORDER BY 编号 DESC LIMIT ?",
                (编号, 限制),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM 同号归档 ORDER BY 编号 DESC LIMIT ?", (限制,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 裁决查(编号: str) -> dict | None:
    """单号回看：账册行 + 裁决流水 + 归档旧行 + 现行行，四轨分开。"""
    conn = 连接()
    try:
        账 = conn.execute(
            "SELECT * FROM 幂等账册 WHERE 报文编号=?", (编号,)
        ).fetchone()
        if not 账:
            return None
        流水 = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 同号裁决 WHERE 报文编号=? ORDER BY 编号", (编号,)
            ).fetchall()
        ]
        归档 = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 同号归档 WHERE 报文编号=? ORDER BY 编号", (编号,)
            ).fetchall()
        ]
        现行 = conn.execute(
            "SELECT * FROM 观测报文 WHERE 报文编号=?", (编号,)
        ).fetchone()
        return {
            "报文编号": 编号,
            "账册": dict(账),
            "流水": 流水,
            "归档": 归档,
            "现行": dict(现行) if 现行 else None,
        }
    finally:
        conn.close()


# ---- 钩子：装载/结栏/贯验串联点 ----

def before_load(batch: dict) -> dict:
    return batch


def after_load(report: dict) -> dict:
    return report


def decide_gate(event: dict, rules: dict) -> str:
    return "入栏"


def before_close(pen_id: str) -> None:
    return None


def after_close(report: dict) -> dict:
    return report


def extra_verify_checks(snapshot: dict) -> list[str]:
    """栏贯验附加核对：账册登记数须等于观测报文数（吃进与入流同票）。"""
    conn = 连接()
    try:
        账 = conn.execute("SELECT COUNT(*) AS c FROM 幂等账册").fetchone()["c"]
        文 = conn.execute("SELECT COUNT(*) AS c FROM 观测报文").fetchone()["c"]
    finally:
        conn.close()
    if 账 == 文:
        return []
    return [f"幂等撕裂：账册登记={账} 观测报文={文}"]
