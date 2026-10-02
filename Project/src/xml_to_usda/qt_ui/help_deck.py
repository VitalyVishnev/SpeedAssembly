"""Bundled in-app help deck content for the Qt shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HelpSlide:
    topic: str
    title: str
    body: str


HELP_SLIDES: tuple[HelpSlide, ...] = (
    HelpSlide(
        topic="Start",
        title="Start",
        body=(
            "Choose a SpeedTree Raw XML file. The output path is filled from the XML name. "
            "If you choose a custom output folder, later XML selections keep that folder and update only the file name."
        ),
    ),
    HelpSlide(
        topic="Presets",
        title="Presets",
        body=(
            "Factory Defaults is always available. Save named presets for repeated operator choices, then overwrite, "
            "delete, import, export, or reset them from the preset menu."
        ),
    ),
    HelpSlide(
        topic="Materials",
        title="Materials",
        body=(
            "Use Geometry and Materials tabs to review repeated part sources, FBX replacements, and Unreal material paths. "
            "Leave rows blank when the source XML or preset default should stay in control."
        ),
    ),
    HelpSlide(
        topic="Run",
        title="Run",
        body=(
            "Refresh Wind Groups when wind settings matter. Generate Dynamic Wind JSON separately, or run Convert to USDA "
            "to write the selected assembly output."
        ),
    ),
)
