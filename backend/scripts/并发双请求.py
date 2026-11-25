"""并发双请求脚本：两路同号并发装载，验证互斥——只有一路入栏，另一路幂等驳回。

用法：python3 backend/scripts/并发双请求.py
退出码：0 = 互斥成立（单行）；1 = 双行/异常。
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

根 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(根))
os.environ.setdefault("数据目录", tempfile.mkdtemp(prefix="探栏并发-"))

from app import seed  # noqa: E402
from app.modules import 报文键幂等 as 幂等  # noqa: E402
from app.services import 装载, 目录  # noqa: E402


def main() -> int:
    seed.初始化库()
    体 = {
        "批次编号": "脚本并发探批",
        "报文": [{
            "报文编号": "dup-script-1",
            "站点键": "站-河东",
            "指标键": "PM25",
            "读数": 33.0,
            "观测时": "2026-11-24T11:00:00Z",
        }],
    }
    闸 = threading.Barrier(2)
    果, 错 = [], []

    def 工():
        try:
            闸.wait(timeout=10)
            果.append(装载.装一批(dict(体)))
        except Exception as e:  # noqa: BLE001
            错.append(repr(e))

    线程 = [threading.Thread(target=工) for _ in range(2)]
    for t in 线程:
        t.start()
    for t in 线程:
        t.join(timeout=30)

    缓冲 = [r for r in 目录.缓冲列表() if r["报文编号"] == "dup-script-1"]
    报文 = [r for r in 目录.报文列表() if r["报文编号"] == "dup-script-1"]
    汇 = 幂等.账册汇总()
    结果 = {
        "异常": 错,
        "两路回执": [{"入栏": r["入栏"], "驳回": r["驳回"], "批次": r["批次编号"]} for r in 果],
        "入栏合计": sum(r["入栏"] for r in 果),
        "驳回合计": sum(r["驳回"] for r in 果),
        "缓冲同号行": len(缓冲),
        "报文同号行": len(报文),
        "账册": 汇,
    }
    过 = (
        not 错
        and 结果["入栏合计"] == 1
        and 结果["驳回合计"] == 1
        and 结果["缓冲同号行"] == 1
        and 结果["报文同号行"] == 1
        and 汇["登记"] == 1
        and 汇["驳回同号"] == 1
    )
    结果["结论"] = "互斥成立：一路入栏一路驳回，缓冲无双行" if 过 else "失败：同号双行或异常"
    print(json.dumps(结果, ensure_ascii=False, indent=2))
    return 0 if 过 else 1


if __name__ == "__main__":
    sys.exit(main())
