# UI Review Workflow

## Role

This document defines how the PySide6 release shell is reviewed and iterated.

## Pairing loop

The UI is developed in a screenshot-driven loop:

1. implement one visual milestone
2. launch the PySide6 shell locally
3. capture 1-2 screenshots
4. review spacing, hierarchy, radius, color, font scale, and balance
5. apply the next polish pass

## Expected screenshot reviews

The first review cadence is:

1. shell bootstrap screenshot review
2. theme/token pass
3. panels/layout pass
4. working flow pass
5. polish pass

## Feedback format

The most useful review comments are short and concrete:

- panel is too large or too small
- title bar is too heavy
- radius is too round or too sharp
- text is too small
- button color is too saturated
- background and panel are too close in value
- spacing is too tight or too loose

The goal is quick iteration from screenshots, not one-shot visual perfection.
