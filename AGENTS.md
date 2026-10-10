# Model selection rule

Choose the model to fit the task's reasoning needs. Prefer the fastest suitable model, and use a stronger model when the expected cost of a mistake or the amount of reasoning warrants it.

- **Simple — `gpt-6-luna`:** small, well-defined edits; routine explanations; straightforward lookups; formatting; and mechanical refactors with clear acceptance criteria.
- **Standard — `gpt-6.1-sol`:** normal feature work, code review, debugging across a few files, test design, and tasks requiring balanced implementation and reasoning. Use this as the default when complexity is uncertain.
- **Complex — `gpt-6-astra`:** architecture or security reviews, high-impact authentication or authorization changes, subtle concurrency or data-integrity bugs, broad cross-cutting changes, difficult root-cause analysis, or decisions with costly failure modes.

Estimate complexity from the task's uncertainty, breadth, dependencies, and consequences—not its wording or requested answer length. Reassess if investigation reveals a deeper or broader problem, and move to a stronger available model when that will materially improve the result. Move to a faster model only when the remaining work is clearly routine and the handoff preserves enough context.

When the runtime permits choosing or changing the model, apply this rule before substantial work and when complexity changes. If it does not expose model switching, continue with the strongest available model and do not claim a switch occurred. Do not delegate or change models solely to make a simple task appear more thorough.
