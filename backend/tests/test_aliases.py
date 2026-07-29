"""成分别名表测试：俗名/代号 → INCI 映射，文本内别名扫描（长别名优先、拉丁大小写无关）。

别名表是 RAG 证据检索与 Agent 工具共用的用户语言入口（04a 审查修复）：
「VC」「377」「蓝铜胜肽」等必须直达对应 INCI，且别名命中优先于子串命中。
"""

from app.services.aliases import ALIAS_INDEX, aliases_in_text


class TestAliasTable:
    def test_required_mappings(self):
        """04a 审查要求的别名都在表里（别名 → INCI 大写）。"""
        expected = {
            "VC": "ASCORBIC ACID", "维C": "ASCORBIC ACID",
            "维生素C": "ASCORBIC ACID", "左旋VC": "ASCORBIC ACID",
            "377": "PHENYLETHYL RESORCINOL", "SymWhite377": "PHENYLETHYL RESORCINOL",
            "维A": "RETINOL", "A醇": "RETINOL",
            "维E": "TOCOPHEROL", "生育酚": "TOCOPHEROL", "维生素E": "TOCOPHEROL",
            "B5": "PANTHENOL", "泛醇": "PANTHENOL", "维生素B5": "PANTHENOL",
            "玻色因": "HYDROXYPROPYL TETRAHYDROPYRANTRIOL",
            "依克多因": "ECTOIN",
            "传明酸": "TRANEXAMIC ACID",
            "水杨酸": "SALICYLIC ACID",
            "烟酰胺": "NIACINAMIDE",
            "阿基瑞林": "ACETYL HEXAPEPTIDE-8",
            "蓝铜胜肽": "COPPER TRIPEPTIDE-1",
            "光甘草定": "GLYCYRRHIZA GLABRA (LICORICE) ROOT EXTRACT",
            "补骨脂酚": "BAKUCHIOL",
            "麦角硫因": "ERGOTHIONEINE",
            "神经酰胺": "CERAMIDE NP",
        }
        for alias, inci in expected.items():
            assert alias in ALIAS_INDEX, f"缺别名：{alias}"
            assert inci in ALIAS_INDEX[alias], f"{alias} 未指向 {inci}"

    def test_hyaluronan_multi_target(self):
        """玻尿酸同时指向透明质酸与透明质酸钠（元组顺序即命中顺序）。"""
        assert ALIAS_INDEX["玻尿酸"] == ("HYALURONIC ACID", "SODIUM HYALURONATE")

    def test_no_single_char_alias(self):
        """别名至少 2 字符，杜绝单字误匹配。"""
        assert all(len(a) >= 2 for a in ALIAS_INDEX)


class TestAliasesInText:
    def test_longest_alias_first(self):
        """「维生素C」优先于「维C」「VC」：长别名先命中，防短别名抢先。"""
        hits = aliases_in_text("维生素C真的能美白吗？")
        assert hits[0][0] == "维生素C"
        assert hits[0][1] == ("ASCORBIC ACID",)

    def test_latin_case_insensitive(self):
        assert aliases_in_text("vc有用吗")[0][1] == ("ASCORBIC ACID",)
        assert aliases_in_text("Symwhite377怎么样")[0][1] == ("PHENYLETHYL RESORCINOL",)

    def test_digit_leading_alias(self):
        """数字开头别名（377）可作为命中项。"""
        assert aliases_in_text("377能美白吗？")[0][1] == ("PHENYLETHYL RESORCINOL",)

    def test_no_alias_empty(self):
        assert aliases_in_text("今天天气怎么样") == []
