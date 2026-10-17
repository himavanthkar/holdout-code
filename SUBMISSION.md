# Submission kit (for the human filling in the form)

- **Repo:** https://github.com/himavanthkar/holdout-code (public)
- **Track:** Version N+1
- **Video:** 1 minute, script in `video_script.md`. Record `python demo.py --replay runs/main --speed 2`, then the 3 charts in `results/`.
- **Teammates:** add everyone on the form.

## Description (paste)

HOLDOUT is a coding agent team that rewrites itself every generation (prompts, playbook, tools, team structure, budget) but keeps a change only when hidden tests it cannot game prove the change is real. We run two arms from the same gen-0 with the same proposals: a Nemotron 3 Super improver plus a red-team "Goodhart agent" that plants cheating diffs. The naive arm keeps whatever raises its visible tests, as most self-improving loops do. The HOLDOUT arm must also pass a parameter-free Ladder gate (Blum & Hardt 2015) on a sealed audit pool scored with EvalPlus plus tests, and it only ever learns accepted/rejected plus a rounded score. Result on our main seed: naive's visible score climbed from 86.7% to 100% while its hidden score fell from 73.3% to 53.3%, and it accepted 2/2 planted cheats. HOLDOUT refused 4/4. On 60 unseen HumanEval+ tasks, naive-final scored 75.0% vs 81.7% for gen-0 and HOLDOUT-final. All calls run on Crusoe Managed Inference, with Nemotron Nano workers and a Nemotron Super improver. Every decision is plain Python on executable evidence. Numbers: `results/results.json`.

## Crusoe feedback (paste, edit freely)

- What worked: the OpenAI-compatible endpoint was a drop-in for the `openai` SDK. Nemotron 3 Nano was fast for worker calls (median about 0.8 s, p95 about 2.7 s over ~2.5k calls), so a 4-generation, two-arm evolution plus a 60-task unseen eval finished in minutes for well under a dollar of tokens (our estimate). `chat_template_kwargs` to turn thinking off worked for Nemotron, Qwen and DeepSeek.
- What we missed: Nemotron 3 Ultra was not in `GET /v1/models` for our key, so we used Nemotron 3 Super as the orchestrator. Nano returns `prompt_tokens_details: null`, so we could not see KV-cache (MemoryAlloy) hits for the model that makes ~99% of our calls; Super returned `cached_tokens` on a few calls. A simple time-to-first-token probe (shared vs shuffled ~1.3k-token prefix) showed no measurable speedup. It would help to have cached-token reporting on every model, plus docs on minimum prefix length and when prefix caching is active.
- Nice to have: published per-model prices in the models list, so agents can budget themselves.
