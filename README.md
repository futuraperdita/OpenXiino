# OpenXiino (FP Remix)

> **Note:** This is a working development fork and should be considered highly unstable. Use [nicl83/OpenXiino](https://github.com/nicl83/OpenXiino) if you're not looking to explore something very new. **Absolutely no support** will be given for this fork until it reaches stability and use in its parent project.

This repository contains a heavily modified, **very work-in-progress** fork of nicl83's [OpenXiino](https://github.com/nicl83/OpenXiino) rewrite of the Palmscape/Xiino "DataServer", which will eventually be used in an unreleased project.

## Why is this necessary?

In its day, Xiino/PalmScape used a "DataServer" proxy that would minify HTML and images so that the browser on the Palm could support the website. The original proxy is long-gone and the code was never open-sourced, but @nicl83 reverse-engineered its proprietary `EBDImage` format (permutations of the Palm pixmap bitmap format) as well as how the client communicates information about the Palm to the client.

Proxies like this appear to have been relatively common on mobile devices even outside of classic PDAs like the Palm. [Opera Mini](https://en.wikipedia.org/wiki/Opera_Mini), for example, still exists today and does pre-rendering of content server-side. This project aims to make Xiino useful for a Palm OS device again, which can be connected via serial (legacy PPP null-modem-style) or 802.11b (for Palm OS 5.x devices).

## Current improvements

The original OpenXiino was meant to be a "MVP" that re-enabled the use of the Xiino browser.

In order to better support some parts of the modern Web, this fork has developed into what is almost a full rewrite:

_Security_:

- Opportunistic attempts at upgrading outbound connections to HTTPS
- Ability to set various client limits, such as overall page weight and request rate limits
- Improved error handling

_Bugfixes & Features_:

- Revised palette system with better perceptual color accuracy using LAB conversion
- Stricter support for Xiino 3.4E HTML tags (e.g. attribute and value-level enforcement)
- Basic SVG support via CairoSVG (which is still a little weird sometimes)
- Basic Cookie support to Xiino specifications
- More accurate compression and dithering algorithms
- Templated `about` and error pages with the proprietary `.xiino` domain (e.g. `http://about.xiino`)

_Performance_:

- `aiohttp` based, async request handling
- `numpy`-vectorized image conversion and compression

_Developer Tools_:

- Docker container support
- A suite of unit tests using `pytest`
- GitHub CI workflow for test suite
- Python-standard logging functionality
- Fully configurable via environment variables

The end result is to try to build an OpenXiino that is a little more "production-grade", such that it could be run as a service for a small PalmOS community.

**Note that JavaScript of any type is still not supported.** The JavaScript implementation of Xiino is basically DHTML-level and is too small for the majority of reason to support JS today, which is for single-page applications written in major frameworks such as React. It's best to think of OpenXiino as a minimal translation layer on already relatively minimal pages. You can use it as a modern TLS-capable proxy to browse the now mostly-HTTPS web without having to worry about the obsolete SSL stack built into Xiino.

I'm maintaining this fork outside of nicl83/OpenXiino until it reaches some stability. After that, I'll ask the original maintainer if they're interested in upstreaming any of these changes.

## Usage

It is recommended to run this fork in the Docker image, which can be built from the `Dockerfile` in this repository. You'll need to provide the environment variables in `.env.sample` either by copying in a `.env` or by setting them in your `docker-compose.yml` or on the Docker command line.

### Built-in pages

To see whether or not OpenXiino itself working correctly, visit `http://about.xiino`. If you see a page, OpenXiino itself is working correctly and talking to your Palm OS device.

## Development

If you're interested in working on this fork, fork it yourself. You'll want to run it outside the repository. To run the server for the first time, create a virtual environment, install dependencies, and execute it:

```bash
python3 -m venv venv && \
source venv/bin/activate && \
pip install -r requirements.txt && \
python3 dataserver.py
```

### Test Suite

Tests are run using `pytest`:

```bash
python3 -m pytest tests/
```

### Using OpenXiino locally

I test most of this fork of OpenXiino directly with a real Palm IIIxe connected over serial via `pppd`, mimicking a 56K modem. Here's an example of how to set up `pppd` on a Linux system, assuming your serial port is symlinked to `/dev/pilot` (it is more likely to be `/dev/ttyUSB0` or `/dev/ttyS0` depending on your system configuration):

```bash
sudo pppd /dev/pilot 57600 192.168.12.1:192.168.12.2 ms-dns 8.8.8.8 proxyarp persist local noauth silent nodetach
```

You'll have `ppp0` appear as an interface. Run `dataserver.py` and set the DataServer on the Palm as `192.168.12.1:8080`.

## License

nicl83's original code is licensed under the more-permissive MIT license; this fork is licensed under the [GNU Affero General Public License 3.0](./LICENSE).

This project, and nicl83's project, are not in any way affiliated with Kazuho Oku or his defunct companies Mobirus, Inc. and ILINX, Inc. The only contact I have had with Kazuho Oku was to politely request on X that he consider open sourcing the client code so I can make changes to it, too.
