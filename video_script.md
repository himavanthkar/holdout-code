# 1-minute video script (HOLDOUT: Code)

Record: `python demo.py --replay runs/main --speed 2` in a large terminal, then the three PNGs in `results/`.
Everything shown was built today. Numbers: read them off the screen / `results/tables.md`, never from memory.

| time | screen | voiceover |
|---|---|---|
| 0:00-0:10 | title panel | "Self-improving agents grade themselves on the tests they optimize. Give a coding team a few visible tests and it learns to cheat them. This is HOLDOUT." |
| 0:10-0:25 | generation 1 scrolling: candidate diffs | "Every generation, a Nemotron Super improver on Crusoe rewrites the team: prompts, playbook, tools, structure. A red-team agent slips in one cheating change. Two arms see the same proposals. Naive keeps whatever raises the visible score. HOLDOUT must also pass a Ladder gate on sealed EvalPlus hidden tests." |
| 0:25-0:45 | the gen-1 verdict lines, then chart_visible_vs_hidden.png | "Here: hardcode the visible inputs. Visible score jumps. Naive accepts it. HOLDOUT's gate rejects it, because the hidden tests did not move. Over four generations naive's visible line climbs while its hidden line drops; HOLDOUT's lines stay together." |
| 0:45-0:55 | REVEAL table + chart_unseen.png | "Then the real proof: 60 HumanEval+ tasks neither arm ever saw. Gen-0, naive-final, HOLDOUT-final." (say the three numbers on screen) |
| 0:55-1:00 | closing panel | "Everyone builds the optimizer. We built the thing that catches it lying." |
