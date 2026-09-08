"""Tests for the ``ctdcast list`` registry-listing verb."""

import argparse
from pathlib import Path

from ctdcast.cli import list as list_cli
from ctdcast.config.people import institutions_with_source


def _ns(registry=None, config=None, search=None, vocabulary=None) -> argparse.Namespace:
    return argparse.Namespace(
        registry=registry, config=config, search=search, vocabulary=vocabulary
    )


def _write_config(tmp_path: Path, cruise_info: dict) -> Path:
    import yaml

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"cruise_info": cruise_info}))
    return cfg


class TestInstitutionsProvenance:
    """The helper is where the merge precedence lives — test it directly."""

    def test_user_directory_entry_shows_as_user_and_overrides_packaged(
        self, tmp_path, monkeypatch
    ) -> None:
        """A ~/.config entry wins over a packaged slug of the same name and reads as 'user'."""
        import yaml

        user_dir = tmp_path / "cfgdir"
        user_dir.mkdir()
        (user_dir / "institutions.yaml").write_text(
            yaml.safe_dump(
                {"institutions": {"uhh": {"name": "Overridden UHH", "edmo_uri": "x"}}}
            )
        )
        monkeypatch.setenv("CTDCAST_CONFIG_DIR", str(user_dir))
        rows = {r["slug"]: r for r in institutions_with_source()}
        assert rows["uhh"]["source"] == "user"
        assert rows["uhh"]["name"] == "Overridden UHH"

    def test_inline_entry_shows_only_with_a_config(self) -> None:
        """An inline cruise_info.institutions entry (own name, no slug) reads as 'inline'."""
        inline = [{"name": "Agencia Estatal", "id": "https://ror.org/003x0zc53"}]
        rows = institutions_with_source(inline=inline)
        inline_rows = [r for r in rows if r["source"] == "inline"]
        assert len(inline_rows) == 1
        assert inline_rows[0]["name"] == "Agencia Estatal"
        assert inline_rows[0]["slug"] == ""  # inline entries are named, not keyed
        # a bare slug string references a registry entry, not an inline one
        assert not [
            r
            for r in institutions_with_source(inline=["uhh"])
            if r["source"] == "inline"
        ]


class TestListVerb:
    def test_bare_list_names_the_three_registries(self, capsys) -> None:
        """`ctdcast list` with no registry prints the three names, not an argparse error."""
        assert list_cli.run(_ns()) == 0
        out = capsys.readouterr().out
        assert "institutions" in out and "platforms" in out and "roles" in out

    def test_institutions_no_config_states_what_was_not_searched(self, capsys) -> None:
        """Without a config the footer says the config-scoped entries were not shown."""
        assert list_cli.run(_ns("institutions")) == 0
        out = capsys.readouterr().out
        assert "packaged" in out
        assert "No config given" in out

    def test_search_matches_on_name_not_only_slug(self, capsys) -> None:
        """--search filters across the name as well as the slug."""
        assert list_cli.run(_ns("institutions", search="Kiel")) == 0  # GEOMAR's name
        out = capsys.readouterr().out
        assert "geomar" in out

    def test_platforms_show_traps(self, capsys) -> None:
        """Platforms list the ambiguous/forbidden traps, with their explanatory messages."""
        assert list_cli.run(_ns("platforms")) == 0
        out = capsys.readouterr().out
        assert "Ambiguous slugs" in out and "meteor" in out
        assert "Forbidden ICES codes" in out

    def test_inline_platform_from_config_is_shown(self, tmp_path, capsys) -> None:
        """A cruise_info.platform dict is listed as an 'inline' vessel."""
        cfg = _write_config(
            tmp_path, {"platform": {"name": "RRS Discovery", "ices_code": "74E3"}}
        )
        assert list_cli.run(_ns("platforms", config=cfg, search="discovery")) == 0
        out = capsys.readouterr().out
        assert "RRS Discovery" in out and "inline" in out

    def test_roles_group_by_axis_and_mark_defaults(self, capsys) -> None:
        """Roles are grouped person vs institution, with the default vocabulary marked."""
        assert list_cli.run(_ns("roles")) == 0
        out = capsys.readouterr().out
        assert "Person roles" in out and "Institution roles" in out
        assert "C89" in out and "(default)" in out

    def test_roles_vocabulary_filters_to_one(self, capsys) -> None:
        """--vocabulary shows a single vocabulary."""
        assert list_cli.run(_ns("roles", vocabulary="W08")) == 0
        out = capsys.readouterr().out
        assert "W08" in out
        assert "C89" not in out  # the other axis is not shown

    def test_unknown_vocabulary_is_an_error(self, capsys) -> None:
        """An unknown --vocabulary exits non-zero and names the valid choices."""
        assert list_cli.run(_ns("roles", vocabulary="BOGUS")) == 1
        assert "Unknown vocabulary" in capsys.readouterr().err

    def test_missing_config_returns_1(self, tmp_path) -> None:
        """A named-but-absent config is a clean error."""
        assert list_cli.run(_ns("institutions", config=tmp_path / "nope.yaml")) == 1

    def test_build_parser_standalone(self) -> None:
        """The parser builds and reads the registry positional and options."""
        ns = list_cli.build_parser(None).parse_args(["roles", "--vocabulary", "C89"])
        assert ns.registry == "roles"
        assert ns.vocabulary == "C89"
