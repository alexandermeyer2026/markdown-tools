# /review-architecture

Review the project's architectural structure and layer boundaries. This is not a general code-quality review — focus exclusively on whether the architecture is coherent: correct layering, consistent gatekeeping patterns, test structure mirroring source structure, and no violations of the patterns the project itself has established.

## Steps

1. **Derive the architecture from the code**

   Do not assume a fixed structure. First read the project to understand what architecture it intends:
   - Run `git ls-files` to map all tracked source files.
   - Read `CLAUDE.md` (if present) and any top-level `README` for stated architectural intent.
   - Identify the layers by looking at top-level directories and their `__init__.py` exports. Infer the intended dependency direction from what each layer imports.
   - Identify any "gateway" or "single point of mutation" patterns by looking for modules that are the only place a particular operation is supposed to happen. These are often signalled by comments, by all callers routing through one function, or by the recent git history centralising logic into one place.

2. **Check import direction**

   For each source file, read its imports and check whether they respect the dependency direction the project has established. Flag any import that crosses a layer boundary in the wrong direction (e.g. a low-level utility importing from a high-level tool, or a data model importing from an application layer).

   Also flag circular imports between any two modules.

3. **Check gateway / single-point-of-mutation patterns**

   If the project routes certain operations through a designated module or function, check that all callers respect this. Look for:
   - Direct construction or manipulation of internal data structures that should go through a factory or mutation API.
   - Callers that bypass the designated API and modify state directly.

   The goal is not to apply a fixed rule but to find the pattern the project uses and check whether it is applied consistently everywhere.

4. **Check test / source mirroring**

   For each non-trivial source module, check whether a corresponding test file exists at the expected mirrored path. Also check the inverse: are there test files whose name corresponds to a source module that no longer exists?

5. **Check for direct field mutation bypassing setters**

   If the project uses objects with setter methods that keep derived state (e.g. serialised representations, computed ranges, caches) in sync with the underlying data, grep for places where the raw fields are assigned directly rather than going through the setter. Bypassing setters breaks the sync invariant.

## Output format

Start with a one-line verdict: **Architecture coherent** or **Architecture violations found**.

Then report findings in three groups:

**Violations** — invariants that are broken right now; these need to be fixed  
**Risks** — patterns that are not yet broken but are fragile or likely to become violations  
**Drift** — test/source mirroring gaps, naming inconsistencies, or stale structure that should be cleaned up  

For each finding include the exact file and line number, what invariant is broken, and the specific fix required. Avoid generic advice — every finding should be directly actionable. End with a short paragraph on overall architectural health.
