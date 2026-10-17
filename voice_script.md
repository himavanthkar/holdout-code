# Voiceover script (about 60 seconds, ~150 words)

Numbers are from `results/results.json` (main run, seed 17) and the README cross-seed table.

## Narration (read verbatim)

Self-improving AI agents grade themselves on the tests they optimize. Give a coding team a few visible tests, and it learns to cheat them.

This is HOLDOUT. Every generation, a Nemotron Super improver on Crusoe rewrites the team: its prompts, playbook, tools and structure. A red-team agent slips in one cheating change. Two arms see the same proposals. The naive arm keeps whatever raises its visible score. HOLDOUT must also pass a Ladder gate on sealed EvalPlus hidden tests.

Generation one: hardcode the visible inputs. The visible score jumps ten points. Naive accepts it. HOLDOUT's gate rejects it, because the hidden tests got worse.

After four generations, naive's visible score hit one hundred percent, while its hidden score fell from seventy-three to fifty-three. HOLDOUT refused every planted cheat: zero of ten, across three seeds.

On sixty unseen HumanEval-plus tasks, naive dropped to seventy-five percent. HOLDOUT stayed at eighty-one point seven.

Everyone builds the optimizer. We built the thing that catches it lying.

## Timing against the screen

| time | screen | line |
|---|---|---|
| 0:00-0:08 | title panel | "Self-improving AI agents ..." |
| 0:08-0:24 | generation 1 candidates scrolling | "This is HOLDOUT ..." |
| 0:24-0:34 | gen-1 verdicts: NAIVE accepted, HOLDOUT REJECTED, explainer | "Generation one ..." |
| 0:34-0:46 | reveal table, then chart_visible_vs_hidden.png | "After four generations ..." |
| 0:46-0:54 | unseen table / chart_unseen.png | "On sixty unseen ..." |
| 0:54-1:00 | closing panel | "Everyone builds the optimizer ..." |

## If you use NotebookLM

Its Audio Overview is a two-host conversation and usually runs longer than a minute, and it paraphrases. Upload this file as the only source, choose the **Brief** format, and paste into "Customize":

> One narrator only, no second host. Read the "Narration (read verbatim)" section word for word, in a calm, confident demo voice. No intro, no outro, no added facts or numbers. Keep it under 65 seconds.

If it still comes out long or adds numbers, use `video/voiceover_say.m4a` instead. It's the same text, read verbatim by macOS `say`, timed to about 60 s.
