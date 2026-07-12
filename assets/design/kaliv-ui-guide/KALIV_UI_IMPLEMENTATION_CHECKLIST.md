# Kaliv UI implementation checklist

## Foundation
- [ ] Semantic dark/light tokens implemented centrally
- [ ] 8 px grid, typography, radii and motion tokens are shared
- [ ] No pure black or pure white large surfaces

## Shell and navigation
- [ ] Brand header uses approved ankh + KALIV wordmark
- [ ] Model/RAG/Tools are grouped separately from primary navigation
- [ ] Header remains readable at 900 px width

## Conversation
- [ ] Assistant identity, timestamp and actions follow the guide
- [ ] User and assistant max-widths are respected
- [ ] Long text remains readable at 65-78 characters per line
- [ ] Composer says “Skriv til Kaliv …”

## States
- [ ] Hover, focus, pressed, disabled, loading, error, offline and empty states exist
- [ ] Kaliv thinking animation is used for generation/tool work
- [ ] Reduced-motion fallback exists

## Accessibility and QA
- [ ] WCAG AA contrast verified
- [ ] 44×44 px minimum targets
- [ ] Full keyboard flow verified
- [ ] 200 % zoom verified
- [ ] Dark and light visually compared with the target mockup
