# Run from demo/: vhs latest-variable.tape
Output ../deliverables/latest-variable.gif

Require uv

Set Shell bash
Set Theme "Catppuccin Mocha"
Set FontFamily "Roboto Mono"
Set FontSize 16
Set Width 1100
Set Height 700
Set Padding 20
Set Framerate 20
Set PlaybackSpeed 2
Set TypingSpeed 60ms
Set CursorBlink false
Set WaitTimeout 3m

Hide
Sleep 500ms
Show
Sleep 500ms

Type "GITHUB_REPO=straubt1/terraform-aws-object-storage \"
Enter
Type "GITHUB_CANDIDATE_REF=latest-variable \"
Enter
Type "uv run --directory ../part2  python -m review"
Enter

Wait /Create a pull request with these suggestions\?/
Sleep 400ms
Type "yes"
Enter
Sleep 12s
