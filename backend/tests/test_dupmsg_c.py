"""争用失败测：两路同号并发装载，不得双双入栏、缓冲不得冒同号双行。"""
import threading

from app.modules import 报文键幂等 as 幂等
from app.services import 装载, 目录


def test_并发同号不双行():
    体 = {
        "批次编号": "并发探批",
        "报文": [{
            "报文编号": "dup-c",
            "站点键": "站-河东",
            "指标键": "PM25",
            "读数": 33.0,
            "观测时": "2026-11-24T11:00:00Z",
        }],
    }
    闸 = threading.Barrier(2)
    果 = []
    错 = []

    def 工():
        try:
            闸.wait(timeout=10)
            果.append(装载.装一批(dict(体)))
        except Exception as e:  # 并发不得炸出异常
            错.append(e)

    线程 = [threading.Thread(target=工) for _ in range(2)]
    for t in 线程:
        t.start()
    for t in 线程:
        t.join(timeout=30)

    assert not 错, f"并发装载抛异常: {错}"
    assert len(果) == 2
    assert sum(r["入栏"] for r in 果) == 1, "两路同号只有一路能入栏"
    assert sum(r["驳回"] for r in 果) == 1, "另一路须被幂等驳回"
    # 库里同号只有一行：缓冲不冒双行
    缓冲 = [r for r in 目录.缓冲列表() if r["报文编号"] == "dup-c"]
    报文 = [r for r in 目录.报文列表() if r["报文编号"] == "dup-c"]
    assert len(缓冲) == 1 and len(报文) == 1
    # 账册登记一次、驳回一次
    汇 = 幂等.账册汇总()
    assert 汇["登记"] == 1 and 汇["驳回同号"] == 1
