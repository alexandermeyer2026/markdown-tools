# /review-project

Review the entire project codebase for code quality, architecture, and cleanliness.

## Steps

1. Discover all source files:
   - Run `find . -type f -name "*.py" | grep -v __pycache__ | grep -v .venv | grep -v .git | sort`

2. Read every source file in full.

3. Produce a structured review covering:

### Architecture & separation of concerns
- Are responsibilities cleanly divided between modules?
- Is there inappropriate coupling between layers?
- Do modules/classes have a single clear purpose?

### Duplicate & redundant logic
- Are there functions or code blocks that do the same thing in multiple places?
- Could any logic be extracted into shared utilities?

### Consistency
- Are naming conventions consistent (files, functions, variables)?
- Are similar problems solved in similar ways across the codebase?
- Are patterns used consistently (e.g. static methods, dataclasses, error handling)?

### Complexity & clarity
- Are there overly complex functions that should be broken up?
- Is anything harder to follow than it needs to be?

### Test coverage
- Which modules or code paths lack tests?
- Are existing tests testing the right things?

## Output format

Group findings by severity:

**Should fix** — clear problems that hurt maintainability or correctness  
**Worth considering** — improvement opportunities with a meaningful upside  
**Minor** — small inconsistencies or style issues  

For each finding, include the file and line number where relevant, and a concrete suggestion for how to address it. Be specific — avoid generic advice. End with a short summary of the overall codebase health.
