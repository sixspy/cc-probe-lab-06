"""失败测乙：装载批次对账须诚实——同号驳回记为驳回，不得计为入栏成功绿。"""
import asyncio

from app.services import 装载, 目录, 统计, 夹具


def test_再灌批次回执与对账诚实():
    装载.装一批(夹具.读取("同号首装样例"))
    再 = 装载.装一批(夹具.读取("同号再灌样例"))
    批次 = 再["批次编号"]
    # 回执本身：入栏 0、驳回 2
    assert 再["入栏"] == 0 and 再["驳回"] == 2
    # 批次列表须带驳回列，驳回不得被作成入栏成功
    行 = [b for b in 目录.装载批次列表() if b["编号"] == 批次]
    assert 行 and 行[0]["入栏"] == 0 and 行[0]["驳回"] == 2
    # 对账：回执与库实一致；驳回未被计为成功
    账 = 统计.装载批次对账(批次)
    assert 账["入流"] == 0 and 账["入栏"] == 0 and 账["驳回"] == 2
    assert 账["实际入流"] == 0 and 账["实际入栏"] == 0
    assert 账["账平"] is True
    assert 账["伪绿"] is False


def test_首装批次对账全绿():
    首 = 装载.装一批(夹具.读取("同号首装样例"))
    账 = 统计.装载批次对账(首["批次编号"])
    assert 账["入栏"] == 1 and 账["坏点"] == 1 and 账["驳回"] == 0
    assert 账["实际入栏"] == 1 and 账["实际坏点"] == 1
    assert 账["账平"] is True and 账["伪绿"] is False


def test_同号裁决只读接口():
    装载.装一批(夹具.读取("同号首装样例"))
    装载.装一批(夹具.读取("同号再灌样例"))
    from app.main import app

    async def go():
        c = app.test_client()
        r = await c.get("/api/同号裁决")
        assert r.status_code == 200
        return await r.get_json()

    数据 = asyncio.run(go())
    assert 数据["策略"] == "切流账册"
    assert 数据["汇总"]["驳回同号"] == 2
    # 现行条数与归档条数分开可读
    assert 数据["现行条数"] == 2
    assert 数据["归档条数"] == 0
    驳回集 = {d["报文编号"] for d in 数据["裁决"] if d["裁决"] == "驳回-同号"}
    assert 驳回集 == {"dup-a", "dup-b"}
