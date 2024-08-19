from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader


class TestComponentPackageLoader:

    def test_load(self) -> None:
        loader = ComponentPackageLoader.load({
            "component.yaml": """
            entry_point: entry_point.py
            callable: dummy_callable
            """,
            "entry_point.py": "dummy_function()"
        })

        assert loader == ({'entry_point': 'entry_point.py', 'callable': 'dummy_callable'}, "dummy_function()", "dummy_callable")

