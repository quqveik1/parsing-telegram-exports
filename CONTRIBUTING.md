# Contributing

Keep the parser dependency-free and include a regression test for behavior changes.

```sh
python3 -m unittest discover -s tests -v
```

Use only invented examples in tests, issues, screenshots, and pull requests. Create a small HTML fixture that reproduces the problem; do not attach a real chat export, even with names removed. Example addresses should use reserved domains such as `example.org`.

The Git ignore rules allow only maintained source files and the fictional demonstration. Add new public files to the allowlist deliberately. Keep local exports and generated archives outside the repository, or under its ignored `output/` directory.

Changes to the meaning of `verification.status` must be reflected in both the README and the skill instructions. A count match must never be described as proof of lossless extraction.
