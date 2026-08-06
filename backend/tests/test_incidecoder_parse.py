"""INCIDecoder 采集器解析器测试：用保存的真实 HTML fixture 测纯解析逻辑。"""

import json
from pathlib import Path

from data.tools.collect_incidecoder import (
    normalize_inci,
    parse_brand_page,
    parse_product_page,
)

FIX = Path(__file__).parent / "fixtures" / "incidecoder"
BRAND_HTML = (FIX / "brand_cerave.html").read_text(encoding="utf-8")
PROD_HTML = (FIX / "product_cerave_moisturizing_cream.html").read_text(encoding="utf-8")


def test_parse_brand_page_products_and_next():
    links, next_offset = parse_brand_page(BRAND_HTML)
    assert links == [
        ("cerave-100-mineral-sunscreen-spf-30", "CeraVe 100% Mineral Sunscreen Spf 30"),
        ("cerave-2-in-1-anti-dandruff-hydrating-shampoo-conditioner",
         "CeraVe 2 In 1 Anti-dandruff Hydrating Shampoo & Conditioner"),
        ("cerave-am-facial-moisturising-lotion-spf-50-for-normal-to-dry-skin",
         "CeraVe AM Facial Moisturising Lotion SPF 50 For Normal To Dry Skin"),
    ]
    assert next_offset == 1


def test_parse_brand_page_last_page_has_no_next():
    html = BRAND_HTML.replace('href="/brands/cerave?offset=1"', 'href="/brands/cerave"')
    links, next_offset = parse_brand_page(html)
    assert len(links) == 3
    assert next_offset is None


def test_parse_product_page_name_and_ordered_ingredients():
    data = parse_product_page(PROD_HTML)
    assert data["name"] == "CeraVe Moisturizing Cream"
    ings = data["ingredients"]
    assert len(ings) == 24
    # 成分按包装降序：水第一，防腐剂乙基己基甘油最末
    assert ings[0]["inci_name"] == "AQUA"
    assert ings[-1]["inci_name"] == "ETHYLHEXYLGLYCERIN"
    # 位次从 1 开始连续编号
    assert [i["position"] for i in ings] == list(range(1, 25))
    # 每个成分带 slug（成分详情页路径），便于后续映射
    assert ings[0]["slug"] == "water"
    assert all(i["slug"] for i in ings)


def test_parse_product_page_strips_zero_width_space():
    data = parse_product_page(PROD_HTML)
    names = [i["inci_name"] for i in data["ingredients"]]
    assert "CAPRYLIC/CAPRIC TRIGLYCERIDE" in names
    assert all("​" not in n for n in names)


def test_parse_product_page_fallback_to_short_list():
    """长列表区段缺失时回退到短列表（listitem 链接顺序同样为降序）。"""
    i = PROD_HTML.find('id="showmore-section-ingredlist-long"')
    html = PROD_HTML[:i] + "</body></html>"
    data = parse_product_page(html)
    assert len(data["ingredients"]) == 6
    assert data["ingredients"][0]["inci_name"] == "AQUA"
    assert [x["position"] for x in data["ingredients"]] == [1, 2, 3, 4, 5, 6]


def test_parse_product_page_empty_on_garbage():
    assert parse_product_page("<html><body>not a product</body></html>")["ingredients"] == []


def test_normalize_inci():
    assert normalize_inci("Caprylic/​Capric Triglyceride") == "CAPRYLIC/CAPRIC TRIGLYCERIDE"
    assert normalize_inci("  Ceteareth-20\n") == "CETEARETH-20"
    assert normalize_inci("Aqua") == "AQUA"
    # 页面活性成分的官方浓度标注要剥掉，否则匹配不上已有 SALICYLIC ACID
    assert normalize_inci("Salicylic Acid (2%)") == "SALICYLIC ACID"
    # 合法括号（植物拉丁名）不动
    assert (normalize_inci("Glycyrrhiza Glabra (Licorice) Root Extract")
            == "GLYCYRRHIZA GLABRA (LICORICE) ROOT EXTRACT")


def test_normalize_inci_decodes_html_entities():
    """页面成分名里的 HTML 实体必须解码（实测泄漏：&#34; &#39; 等进入成分名）。"""
    assert normalize_inci("&#34;AQUA / WATER") == "AQUA / WATER"
    assert normalize_inci("NIACINAMIDE&#34;") == "NIACINAMIDE"
    assert normalize_inci("&#34;D&#39;ALPHA VITAMIN E") == "D'ALPHA VITAMIN E"
    assert (normalize_inci("Silybum Marianum (Lady&#39;s Thistle) Extract")
            == "SILYBUM MARIANUM (LADY'S THISTLE) EXTRACT")
    assert normalize_inci("PARFUM / FRAGRANCE &#34;") == "PARFUM / FRAGRANCE"
    assert normalize_inci("Cera Alba/Beeswax/Cire d&#39;Abeille") == "CERA ALBA/BEESWAX/CIRE D'ABEILLE"


def test_parse_product_page_decodes_entities_in_ingredients():
    """构造输入：长列表锚文本带 &#34;/&#39; 实体 → 解析出的成分名必须干净。"""
    html = ('<html><body><h1>Brand X P</h1>'
            '<div id="showmore-section-ingredlist-long">'
            '<div class="ingred-long  "><div class="ingred-header">'
            '<a href="/ingredients/water" class="product-long-ingred-link x">&#34;Aqua / Water</a>'
            '</div></div>'
            '<div class="ingred-long  "><div class="ingred-header">'
            '<a href="/ingredients/niacinamide" class="product-long-ingred-link x">Niacinamide&#34;</a>'
            '</div></div>'
            '<div class="ingred-long  "><div class="ingred-header">'
            '<a href="/ingredients/barley" class="product-long-ingred-link x">Hordeum Vulgare Extract\\Extrait d&#39;Orge</a>'
            '</div></div>'
            '</div></body></html>')
    data = parse_product_page(html)
    names = [i["inci_name"] for i in data["ingredients"]]
    assert names == ["AQUA / WATER", "NIACINAMIDE", "HORDEUM VULGARE EXTRACT\\EXTRAIT D'ORGE"]
    assert all("&" not in n and '"' not in n for n in names)
