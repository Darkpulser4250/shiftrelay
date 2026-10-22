# Optional YouTube TV bridge

Copyright (c) 2026 ShiftRelay contributors.

The source in this directory is licensed under **GPL-3.0-only**, with no warranty. See [LICENSE](LICENSE). You may redistribute and modify it under that license. This independent optional service uses pyytlounge 3.4.0, whose bundled LICENSE is GPL version 3, despite an inconsistent MIT classifier in its package metadata. The actual license text is retained as the authority.

The core proxy and portal remain under the root MIT license. They do not import this bridge or pyytlounge. The processes exchange a minimal, data-only status file. The bridge has its own image, source directory and private state volume.

Dependencies are installed unmodified from PyPI. Their licenses remain applicable. No iSponsorBlockTV implementation is vendored. iSponsorBlockTV is credited as prior art for native YouTube TV control and protocol behavior, including the meaning of ad-state transitions. ShiftRelay's controller, recovery journal, status schema and tests are original.

Primary references:

- https://github.com/FabioGNR/pyytlounge
- https://github.com/FabioGNR/pyytlounge/blob/master/LICENSE
- https://github.com/dmunozv04/iSponsorBlockTV

This bridge is not affiliated with YouTube or the protocol library authors. Device compatibility is not established merely by installing the library.
