"""Unit tests for the Stern ingester's pure helpers.

The integration leg (real PDF + chunk count) is covered by the smoke run
``make ingest-stern``. We don't pin the chunk count in CI because Stern is a
user-provided personal copy not present in fresh checkouts.
"""

from __future__ import annotations

from tongue_doctor.knowledge.ingest.sources.stern import (
    _slugify,
    chapter_ranges_from_toc,
)


def test_slugify_handles_common_cases() -> None:
    assert _slugify("Chest Pain") == "chest_pain"
    assert _slugify("Kidney Injury, Acute") == "kidney_injury_acute"
    assert _slugify("AIDS/HIV Infection") == "aids_hiv_infection"
    assert _slugify("Cough, Fever, and Respiratory Infections") == (
        "cough_fever_and_respiratory_infections"
    )
    assert _slugify("Headache") == "headache"
    # Empty / pathological inputs fall back to "section".
    assert _slugify("") == "section"
    assert _slugify("   ") == "section"
    assert _slugify("***") == "section"


def test_chapter_ranges_filters_front_matter_and_computes_end_pages() -> None:
    # Stern's actual TOC shape: front matter at level 1 too, then numbered
    # chapters, then "Index". Only the numbered chapters should survive, with
    # end pages computed from the next entry minus one.
    toc: list[list[object]] = [
        [1, "Cover", 1],
        [1, "Title Page", 2],
        [1, "Contents", 6],
        [1, "Preface", 10],
        [1, "1. Diagnostic Process", 14],
        [1, "2. Screening and Health Maintenance", 22],
        [1, "3. Abdominal Pain", 40],
        [1, "9. Chest Pain", 164],
        [1, "33. Wheezing and Stridor", 600],
        [1, "Index", 618],
    ]
    ranges = chapter_ranges_from_toc(toc, total_pages=625)

    assert [r[0] for r in ranges] == [1, 2, 3, 9, 33]
    # Each chapter's end is next-entry-minus-one.
    by_num = {r[0]: r for r in ranges}
    assert by_num[1] == (1, "Diagnostic Process", 14, 21)
    assert by_num[2] == (2, "Screening and Health Maintenance", 22, 39)
    assert by_num[3] == (3, "Abdominal Pain", 40, 163)
    assert by_num[9] == (9, "Chest Pain", 164, 599)
    # Last chapter: bounded by Index, not by total_pages.
    assert by_num[33] == (33, "Wheezing and Stridor", 600, 617)


def test_chapter_ranges_handles_missing_index() -> None:
    # If there's no entry past the last chapter, end falls back to total_pages.
    toc: list[list[object]] = [
        [1, "1. Foo", 10],
        [1, "2. Bar", 20],
    ]
    ranges = chapter_ranges_from_toc(toc, total_pages=50)
    assert ranges == [(1, "Foo", 10, 19), (2, "Bar", 20, 50)]


def test_chapter_ranges_skips_subsection_levels() -> None:
    # Level-2 entries (subsections under a chapter) must be ignored.
    toc: list[list[object]] = [
        [1, "1. Foo", 10],
        [2, "1.1 Subsection", 11],
        [1, "2. Bar", 20],
    ]
    ranges = chapter_ranges_from_toc(toc, total_pages=30)
    assert ranges == [(1, "Foo", 10, 19), (2, "Bar", 20, 30)]


def test_chapter_ranges_clamps_inverted_ranges() -> None:
    # Defensive: never return end < start.
    toc: list[list[object]] = [[1, "1. Last", 50]]
    ranges = chapter_ranges_from_toc(toc, total_pages=40)
    assert ranges == [(1, "Last", 50, 50)]
