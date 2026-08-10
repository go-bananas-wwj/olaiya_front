"""修丽可官网采集器解析测试：sitemap 枚举（内网 loc 只取路径、/mobile/ 跳过）与产品页字段。"""

from data.tools import collect_skinceuticals_cn as sc

SITEMAP = """<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>http://192.168.1.9:9010/</loc></url>
  <url><loc>http://192.168.1.9:9010/productdtl/productdtl-CEferulic.html</loc></url>
  <url><loc>http://192.168.1.9:9010/productdtl/productdtl-HydratingB5.html</loc></url>
  <url><loc>http://192.168.1.9:9010/mobile/productdtl/productdtl-CEferulic.html</loc></url>
  <url><loc>https://www.skinceuticals.com.cn/productdtl/productdtl-CEferulic.html</loc></url>
  <url><loc>http://192.168.1.9:9010/productlist/productlist-jh.html</loc></url>
</urlset>"""

PRODUCT_OK = """<html><body>
<div class="ProductDtlTopDescText1 Js_ProName2">修丽可CE经典抗氧瓶 透白又细嫩</div>
<div class="ProductDtlTopDescText2"><h1 class="Js_ProName1">修丽可維生素CE复合焕颜精华液</h1></div>
<div class="ProductDtlMoney"><span class="span_2 Js_DtlPrice">¥ 1720.00</span></div>
<div class="CapacityWrap Js_Capacity">30ml</div>
<div class="StarProductMoney Js_Price">¥ 1720.00</div>
</body></html>"""

PRODUCT_NO_PRICE = """<html><body>
<div class="ProductDtlTopDescText2"><h1 class="Js_ProName1">修丽可某产品</h1></div>
<div class="CapacityWrap Js_Capacity">50ml</div>
</body></html>"""


def test_parse_sitemap_desktop_only_deduped():
    slugs = sc.parse_sitemap(SITEMAP)
    assert slugs == ["CEferulic", "HydratingB5"]  # 首页/列表页/mobile 镜像/重复 loc 均排除


def test_parse_sitemap_empty_on_garbage():
    assert sc.parse_sitemap("<html>not a sitemap</html>") == []


def test_parse_product_page_fields():
    d = sc.parse_product_page(PRODUCT_OK)
    assert d["name_cn"] == "修丽可維生素CE复合焕颜精华液"
    assert d["subtitle"] == "修丽可CE经典抗氧瓶 透白又细嫩"
    assert d["price"] == 1720.0
    assert d["spec"] == "30ml"


def test_parse_product_page_missing_price_is_none():
    d = sc.parse_product_page(PRODUCT_NO_PRICE)
    assert d["price"] is None  # 缺价格不猜，落 None 由采集层记失败
    assert d["name_cn"] == "修丽可某产品"
    assert d["spec"] == "50ml"
