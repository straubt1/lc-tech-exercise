Output demo.gif
Require uv

Set Shell bash
Set Theme "Catppuccin Mocha"
Set FontSize 16
Set FontFamily "Roboto Mono"
Set Width 1200
Set Height 800
Set Padding 20
Set Framerate 30
Set PlaybackSpeed 0.75
Set TypingSpeed 25ms
Set WaitTimeout 30s


Type "GITHUB_CANDIDATE_REF=latest-variable uv run --directory part2 python -m review"
Enter


Wait /Create a pull request with these suggestions?/
Type "no"
Enter
Sleep 3s