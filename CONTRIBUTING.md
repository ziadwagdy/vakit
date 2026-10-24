# Contributing

Keep the runtime based on Ubuntu packages and the Python standard library plus PyGObject. Run the deterministic tests and GTK smoke check documented in the README before opening a pull request. Include the Ubuntu/Python version tested.

Do not commit settings, delivery history, location caches, credentials, APKs or audio. The public-file check does not replace reviewing `git diff --cached`. Use synthetic locations/data in tests. Network/audio-download tests must remain opt-in.

Network changes must keep certificate verification, pre-request host restrictions, redirect validation, timeouts and response limits. Upstream data must never select arbitrary filesystem paths or commands. Installer subprocesses must use argument arrays, fixed absolute system executables and no shell.

To update the pinned Diyanet APK checksum, independently retrieve it from the official page over verified HTTPS, inspect the exact five expected media entries and their sizes, confirm provenance, run silent decoding, and document the review date/hash. Do not bypass mismatches or automatically trust a newly returned digest.

Third-party recordings/data are outside the MIT license. Do not add them to a release without establishing required redistribution permissions.
