"""Token-aware chunker unit tests.

These pin the size + overlap contract so a future tweak to packing logic doesn't
silently produce 50-token or 1500-token chunks. They also pin the location
propagation guarantee (every emitted chunk carries the section's location string,
which is the citation handle for the Reasoner downstream).
"""

from __future__ import annotations

from tongue_doctor.knowledge.chunkers import (
    Section,
    chunk_sections,
    count_tokens,
)


def test_short_section_emits_single_chunk_with_location():
    sections = [
        Section(title="Etiology", text="Brief paragraph.", location="NBK1#etiology"),
    ]
    out = chunk_sections(sections)
    assert len(out) == 1
    assert out[0].section == "Etiology"
    assert out[0].location == "NBK1#etiology"
    assert out[0].token_count == count_tokens("Brief paragraph.")


def test_long_section_packs_into_target_windows_with_overlap():
    paragraph = (
        "Stable angina is chest discomfort that occurs predictably with exertion "
        "and is relieved by rest or nitroglycerin. The pathophysiology involves a "
        "fixed coronary lesion that limits flow during increased myocardial demand."
    )
    sections = [
        Section(
            title="Pathophysiology",
            text="\n\n".join([paragraph] * 30),
            location="NBK1#pathophys",
        )
    ]
    out = chunk_sections(sections, target_tokens=400, max_tokens=500, overlap_tokens=60)
    assert len(out) >= 2, "long section should split into multiple windows"
    for payload in out:
        assert payload.token_count <= 500 + 100, (
            f"chunk {payload.ord} exceeds budget: {payload.token_count}"
        )
        assert payload.section == "Pathophysiology"
        assert payload.location == "NBK1#pathophys"


def test_empty_section_skipped():
    sections = [Section(title="Empty", text="   \n\n\t  ", location="NBK1#empty")]
    assert chunk_sections(sections) == []


def test_chunk_ord_is_monotonic_across_sections():
    sections = [
        Section(title="A", text="alpha paragraph.", location="loc:a"),
        Section(title="B", text="beta paragraph.", location="loc:b"),
        Section(title="C", text="gamma paragraph.", location="loc:c"),
    ]
    out = chunk_sections(sections)
    ords = [p.ord for p in out]
    assert ords == sorted(ords)
    assert len(set(ords)) == len(ords)
