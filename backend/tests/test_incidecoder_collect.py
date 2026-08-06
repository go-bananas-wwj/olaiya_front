"""INCIDecoder 采集器行为测试：熔断、空解析计数、负缓存、品牌映射（FakeFetcher 注入，不走网络）。"""

import json

import pytest

from data.tools import collect_incidecoder as ci


# —— 最小可用 HTML 片段 ——
BRAND_OK = ('<html><body>'
            '<a href="/products/brand-x-p1" class="klavika simpletextlistitem ">Brand X P1</a>'
            '<a href="/products/brand-x-p2" class="klavika simpletextlistitem ">Brand X P2</a>'
            '<a href="/products/brand-x-p3" class="klavika simpletextlistitem ">Brand X P3</a>'
            '<a href="/products/brand-x-p4" class="klavika simpletextlistitem ">Brand X P4</a>'
            '</body></html>')
PROD_OK = ('<html><body><h1>Brand X P</h1>'
           '<div id="showmore-section-ingredlist-long">'
           '<div class="ingred-long  "><div class="ingred-header">'
           '<a href="/ingredients/water" class="product-long-ingred-link x">Aqua</a>'
           '</div></div></div></body></html>')
PROD_EMPTY = '<html><body><h1>Brand X P</h1><p>no list here</p></body></html>'


class FakeFetcher:
    """按 URL 排队返回预设 HTML；记录请求次数。"""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str) -> str:
        self.calls.append(url)
        if url not in self.pages:
            raise FileNotFoundError(url)
        return self.pages[url]


@pytest.fixture()
def raw_root(tmp_path, monkeypatch):
    root = tmp_path / "raw" / "incidecoder"
    monkeypatch.setattr(ci, "OUT_ROOT", root)
    return root


def _brand_url(slug="brand-x"):
    return f"{ci.BASE}/brands/{slug}"


def test_consecutive_empty_parses_trip_circuit(raw_root):
    """连续 3 个详情页解析为空 → 熔断（HTTP 200 不应重置空解析计数）。"""
    fetcher = FakeFetcher({_brand_url(): BRAND_OK,
                           f"{ci.BASE}/products/brand-x-p1": PROD_EMPTY,
                           f"{ci.BASE}/products/brand-x-p2": PROD_EMPTY,
                           f"{ci.BASE}/products/brand-x-p3": PROD_EMPTY,
                           f"{ci.BASE}/products/brand-x-p4": PROD_OK})
    with pytest.raises(ci.CircuitOpen):
        ci.collect_brand(fetcher, "brand-x")
    # 第 4 个产品不应再请求
    assert f"{ci.BASE}/products/brand-x-p4" not in fetcher.calls


def test_empty_parse_streak_resets_on_success(raw_root):
    """空解析与成功交替 → 不熔断，空解析计入 failed 并记 _failures.jsonl。"""
    fetcher = FakeFetcher({_brand_url(): BRAND_OK,
                           f"{ci.BASE}/products/brand-x-p1": PROD_EMPTY,
                           f"{ci.BASE}/products/brand-x-p2": PROD_OK,
                           f"{ci.BASE}/products/brand-x-p3": PROD_EMPTY,
                           f"{ci.BASE}/products/brand-x-p4": PROD_OK})
    stats = ci.collect_brand(fetcher, "brand-x")
    assert stats["new"] == 2 and stats["failed"] == 2
    lines = (raw_root / "_failures.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "成分解析为 0" in json.loads(lines[0])["reason"]


def test_empty_brand_page_is_failure_not_silent_success(raw_root):
    """品牌列表页解析为 0：记 _failures.jsonl + failed 计数，不得静默正常结束。"""
    fetcher = FakeFetcher({_brand_url(): '<html><body>oops</body></html>'})
    stats = ci.collect_brand(fetcher, "brand-x")
    assert stats["hits"] == 0 and stats["failed"] == 1
    lines = (raw_root / "_failures.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["brand"] == "brand-x" and "品牌列表页" in rec["reason"]


def test_permanent_404_negative_cache_skips_on_resume(raw_root):
    """续采时 _failures.jsonl 里的 404 记录直接跳过（不再请求）；解析为空类不跳过。"""
    raw_root.mkdir(parents=True)
    with (raw_root / "_failures.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps({"brand": "brand-x", "url": f"{ci.BASE}/products/brand-x-p1",
                            "reason": "404"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"brand": "brand-x", "url": f"{ci.BASE}/products/brand-x-p2",
                            "reason": "成分解析为 0，疑似结构变更或拦截"}, ensure_ascii=False) + "\n")
    fetcher = FakeFetcher({_brand_url(): BRAND_OK,
                           f"{ci.BASE}/products/brand-x-p2": PROD_EMPTY,
                           f"{ci.BASE}/products/brand-x-p3": PROD_OK,
                           f"{ci.BASE}/products/brand-x-p4": PROD_OK})
    stats = ci.collect_brand(fetcher, "brand-x")
    # p1（404 永久失败）不再请求；p2（空解析类）仍会重试
    assert f"{ci.BASE}/products/brand-x-p1" not in fetcher.calls
    assert f"{ci.BASE}/products/brand-x-p2" in fetcher.calls
    assert stats["skipped"] >= 1


class FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}

    def get(self, url, timeout=30):
        return self.responses.pop(0)


@pytest.fixture()
def no_sleep(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)


def test_fetcher_429_cooldown_then_circuit(no_sleep):
    f = ci.Fetcher(delay=0, cooldown=0)
    f._session = FakeSession([FakeResp(429), FakeResp(429)])
    with pytest.raises(ci.CircuitOpen):
        f.get("http://x")


def test_fetcher_429_recovers_after_cooldown(no_sleep):
    f = ci.Fetcher(delay=0, cooldown=0)
    f._session = FakeSession([FakeResp(429), FakeResp(200, "ok")])
    assert f.get("http://x") == "ok"


def test_fetcher_404_raises_file_not_found(no_sleep):
    f = ci.Fetcher(delay=0, cooldown=0)
    f._session = FakeSession([FakeResp(404)])
    with pytest.raises(FileNotFoundError):
        f.get("http://x")


def test_fetcher_consecutive_timeouts_circuit(no_sleep):
    f = ci.Fetcher(delay=0, cooldown=0)

    class TimeoutSession(FakeSession):
        def get(self, url, timeout=30):
            raise TimeoutError("boom")

    f._session = TimeoutSession([])
    with pytest.raises(ci.CircuitOpen):
        f.get("http://x")


def test_brand_mapping_uses_canonical_cn_names():
    """品牌映射对齐库内既有主名（纯中文优先；OLAY/SK-II/雅诗兰黛/资生堂沿用库内既有字符串）。"""
    assert ci.BRANDS["cerave"] == "适乐肤"
    assert ci.BRANDS["la-roche-posay"] == "理肤泉"
    assert ci.BRANDS["skinceuticals"] == "修丽可"
    assert ci.BRANDS["lancome"] == "兰蔻"
    assert ci.BRANDS["kiehls"] == "科颜氏"
    assert ci.BRANDS["kerastase"] == "卡诗"
    assert ci.BRANDS["helena-rubinstein"] == "赫莲娜"
    assert ci.BRANDS["loreal"] == "巴黎欧莱雅"
    assert ci.BRANDS["olay"] == "OLAY 玉兰油"
    assert ci.BRANDS["sk-ii"] == "SK-II"
