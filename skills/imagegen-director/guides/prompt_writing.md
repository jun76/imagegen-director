# Writing the prompts (L4)

Read this before writing any chunk, together with the project's `project.yaml` (purpose),
`notes.md`, `rules.yaml` and `library/rules/universal.yaml`.

## Input

`scripts/show.py --project <dir> --chunk K` prints a chunk of sampled rows grouped by leaf. Each row is one
image: the leaf subject plus one value per axis. Write one prompt per row into
`<dir>/l4_raw/chunk_<KKK>.txt` as `<id> <prompt>` lines, then run
`scripts/assemble.py --project <dir> --check`.

## Principles

- **The subject comes first.** Someone looking at the image must be able to tell what the leaf
  subject is. Never trade it away for an axis value.
- **Axis values are hints, not literal instructions.** When values contradict each other or the
  subject, find an interpretation that works as an image and absorb the contradiction:
  - "endless darkness" x "crowd or many" -> many tiny specks of light scattered through the dark
  - "video call" x "vast horizon" x "dust" -> a call screen showing someone in a vast dusty wasteland
  - "Venn diagram" x "product photo on white background" -> an acrylic block printed with a Venn diagram
  - "office meeting" x "ancient" -> elders holding council in an ancient settlement
  Drop a value only when nothing works.
- **media is the look, not an object.** Never name a capture device (DSLR, smartphone, security
  camera, dashcam, webcam); models draw the device into the picture. Describe the look:
  "professional photograph with shallow depth of field", "casual handheld snapshot with flat
  automatic exposure", "grainy surveillance video frame with a timestamp overlay".
- **Many means a group with gaps.** Never "countless", "swarm", "thousands of". For subjects in
  the project's sensitive groups, avoid mass wording entirely.
- **Degradations must appear.** If `quality` is not clean, put the degradation in the prompt.
- **Region and era show in concrete things**: people, clothing, buildings, tools, writing. Not a
  list of stereotyped symbols.
- **Constants go into every prompt** in natural wording (they are in each row's axes).
- No quality incantations ("masterpiece", "8k", ...), no real people, brands, artists or works.
  If text must appear in the image, give a short string in quotes.
- Phrase death and damage as traces and aftermath; no gore.

## Form

- One flat English sentence or two, about 20-40 words. Lead with the medium (as a look) and the
  subject, then viewpoint, framing, light, color, state, and degradation.
- Vary the wording. Rotate phrasings for recurring values so the set does not repeat one formula.
- Model-agnostic: no model-specific syntax, weights, or negative prompts.

## After writing

`scripts/assemble.py --project <dir> --check` must report 0 violations before moving on. If a rule fires,
rewrite the prompt; do not weaken the rule unless the user agrees that the rule is wrong.
