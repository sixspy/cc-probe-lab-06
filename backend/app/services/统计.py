from __future__ import annotations
from app.db import 连接


def 报文命运() -> dict:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 命运, COUNT(*) AS c FROM 观测报文 GROUP BY 命运"
        ).fetchall()
        return {r["命运"]: r["c"] for r in rows}
    finally:
        conn.close()


def 缓冲命运() -> dict:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 命运, COUNT(*) AS c FROM 入栏缓冲 GROUP BY 命运"
        ).fetchall()
        return {r["命运"]: r["c"] for r in rows}
    finally:
        conn.close()


def 按站点报文() -> dict:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 站点键, COUNT(*) AS c FROM 观测报文 GROUP BY 站点键"
        ).fetchall()
        return {r["站点键"]: r["c"] for r in rows}
    finally:
        conn.close()


def 装载批次摘要(限制: int = 20) -> list[dict]:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 编号,时刻,入流,入栏,坏点,驳回,归档 FROM 装载批次 ORDER BY 时刻 DESC LIMIT ?",
            (限制,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 结栏批次摘要(限制: int = 20) -> list[dict]:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 编号,栏号,时刻,汇总数 FROM 结栏批次 ORDER BY 时刻 DESC LIMIT ?",
            (限制,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 按指标汇总() -> dict:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 指标键, COUNT(*) AS c, COALESCE(AVG(均值),0) AS 均 FROM 站点汇总账 GROUP BY 指标键"
        ).fetchall()
        return {r["指标键"]: {"笔数": r["c"], "均值": r["均"]} for r in rows}
    finally:
        conn.close()


def 装载批次对账(批次编号: str) -> dict:
    """装载批次对账：回执（入流/入栏/坏点/驳回/归档）与库实逐格核对。

    伪绿：回执把驳回/归档计成了入流或入栏成功（回执成功数与库实不符）。
    账平：回执与库实一致，且 入栏+坏点==入流，驳回未被计为成功。
    """
    conn = 连接()
    try:
        批 = conn.execute("SELECT * FROM 装载批次 WHERE 编号=?", (批次编号,)).fetchone()
        if not 批:
            return {"批次编号": 批次编号, "错误": "批次不存在", "账平": False, "伪绿": False}
        列 = set(批.keys())
        驳回 = 批["驳回"] if "驳回" in 列 else 0
        归档 = 批["归档"] if "归档" in 列 else 0
        实入流 = conn.execute(
            "SELECT COUNT(*) AS c FROM 观测报文 WHERE 批次编号=?", (批次编号,)
        ).fetchone()["c"]
        实入栏 = conn.execute(
            "SELECT COUNT(*) AS c FROM 观测报文 WHERE 批次编号=? AND 命运 IN ('已入栏','已汇总')",
            (批次编号,),
        ).fetchone()["c"]
        实坏点 = conn.execute(
            "SELECT COUNT(*) AS c FROM 观测报文 WHERE 批次编号=? AND 命运='已坏点'",
            (批次编号,),
        ).fetchone()["c"]
        伪绿 = (批["入流"] != 实入流) or (批["入栏"] != 实入栏) or (批["坏点"] != 实坏点)
        账平 = (not 伪绿) and (批["入栏"] + 批["坏点"] == 批["入流"])
        return {
            "批次编号": 批次编号,
            "入流": 批["入流"], "入栏": 批["入栏"], "坏点": 批["坏点"],
            "驳回": 驳回, "归档": 归档,
            "实际入流": 实入流, "实际入栏": 实入栏, "实际坏点": 实坏点,
            "账平": 账平,
            "伪绿": 伪绿,
            "说明": "回执与库实一致，驳回未计为成功" if 账平 else "撕裂：回执与库实不符，驳回疑被计为成功",
        }
    finally:
        conn.close()
