# Vendored Fastnet captures: provenance

All captures are real B&G Fastnet bus recordings (H2000/Hydra buses) published under the MIT
licence by their authors. They are vendored unchanged as test fixtures. Licences are copied
alongside as `LICENSE-pyfastnet` and `LICENSE-fastnet2ip`.

Format: one burst of bytes per line, lower-case hex with no separators, no timestamps
(pyfastnet `captures/README.md`). Lines are not frame-aligned, so always feed them through a
framer. `jabuka.ingest.fastnet_framing.load_capture` reads this format.

| Repository | Commit (pinned) | Licence |
|---|---|---|
| https://github.com/ghotihook/pyfastnet | `59bc23be0dbd797ce12d5dc5e0389583dd52f92b` | MIT (`LICENSE-pyfastnet`) |
| https://github.com/ghotihook/fastnet2ip | `9e6ac4495ec6e1482e4094e093de2e18f009b216` (3.3.1) | MIT (`LICENSE-fastnet2ip`) |

Raw download URL pattern:

- `https://raw.githubusercontent.com/ghotihook/pyfastnet/59bc23be0dbd797ce12d5dc5e0389583dd52f92b/captures/<NAME>`
- `https://raw.githubusercontent.com/ghotihook/fastnet2ip/9e6ac4495ec6e1482e4094e093de2e18f009b216/tests/data/<NAME>`

| File | Repo | Original path | File bytes | sha256 |
|---|---|---|---:|---|
| big.txt | pyfastnet | `captures/big.txt` | 42600 | `92867a01cda430de66816177754850ed31710188aae43d5b3a0f82ac19e61943` |
| big_with_ap_actions.txt | pyfastnet | `captures/big_with_ap_actions.txt` | 96740 | `52f9fd8319f9d6310f6a49b381a8e2df576c88877101a02034292c3f3310bb61` |
| example1_fastnet_data.txt | pyfastnet | `captures/example1_fastnet_data.txt` | 126380 | `6faafc177eb12be43d74de37d07870f65f76e481a40fca43e438c6681bd5bfee` |
| example2_fastnet_data.txt | pyfastnet | `captures/example2_fastnet_data.txt` | 133775 | `72d21337af8b890f8ecec540f4c8172cb878c7e9e7ddfd3b58995bdfc8b2e1c0` |
| heel-port.txt | pyfastnet | `captures/heel-port.txt` | 7525 | `1d30f54221f17cdaae2570aa397d2ffcb1ad34fce39e386a3f403cd2234778fd` |
| heel-stb.txt | pyfastnet | `captures/heel-stb.txt` | 19279 | `a19e5a9f0a91f6e5719340970d47393bdc8a1bfea0325d53634b018ecdea7f7a` |
| trim-neg.txt | pyfastnet | `captures/trim-neg.txt` | 7277 | `cb00e6207f53a8d02a7b2fc0f6949d743cb54c97c1f9864f52da69309bbb142e` |
| trim-pos.txt | pyfastnet | `captures/trim-pos.txt` | 8519 | `82f639af2ba8feb0ec771d037ce06194249a5bff04ce47048c2538ec68f8e71a` |
| ap_backlight_20260514.txt | fastnet2ip | `tests/data/ap_backlight_20260514.txt` | 120042 | `9a143af1ffbc2c2749e1914350325d3163c4a1718b8bd6f55cbf9092152d2c3a` |
| rawfn-20260502-011827.txt | fastnet2ip | `tests/data/rawfn-20260502-011827.txt` | 176072 | `54bc6e49652cce4378638e1f61af3d1f4384000825ac4070682092de6126ccb5` |

Note: fastnet2ip's `tests/data/big.txt` is byte-identical to pyfastnet's `captures/big.txt`
(verified with a byte comparison), so it is vendored once.

Why these two fastnet2ip captures: `rawfn-20260502-011827.txt` carries Heading (0x49) frames with
layout `°M` and with layout `None`, so it is the M/T `?` test case; `ap_backlight_20260514.txt`
carries Light Intensity (0xC9) frames and autopilot traffic.

Golden `FrameBuffer(project=True)` queue lengths (pyfastnet 3.2.1), asserted by
`tests/test_framing_equivalence.py`: big 937, big_with_ap_actions 2018, example1 2630,
example2 2801, heel-port 164, heel-stb 422, trim-neg 161, trim-pos 189, ap_backlight 2433,
rawfn 3392.
