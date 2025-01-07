# OpenXiino (FP Remix)

> **Note:** This is a working development fork and should be considered highly unstable. Use [nicl83/OpenXiino](https://github.com/nicl83/OpenXiino) if you're not looking to explore something very new. **Absolutely no support** will be given for this fork until it reaches stability and use in its parent project.

This repository contains a heavily modified, **very work-in-progress** fork of the [OpenXiino](https://github.com/nicl83/OpenXiino) rewrite of the Palmscape/Xiino "DataServer", which will eventually be used in an unreleased project.

Proxies like this appear to have been relatively common on mobile devices even outside of classic PDAs like the Palm. Opera Mini, for example, existed well into the iPhone 5 era and did some minification of images and content on real smartphones. This project aims to make Xiino useful for a Palm OS device again, which can be connected via serial (legacy PPP null-modem-style) or 802.11b (for Palm OS 5.x devices).

## Current changes from the original OpenXiino

The original OpenXiino was meant to be a "MVP" for using the Xiino browser.

In order to better support some parts of the modern Web, this fork is developing a series of upgrades:

- Docker container support
- Fully configurable via environment variables
- `aiohttp` based, async request handling
- `numpy`-vectorized image conversion and compression
- Better image conversion using human-perceptual color algorithms and dithering
- Improved error handling
- Ability to set various client limits, such as overall page weight and request rate limits
- Python-standard logging functionality
- Templated `about` and error pages with the proprietary `.xiino` domain.
- Basic SVG support via CairoSVG
- Basic Cookie support to Xiino specifications
- Stricter support for Xiino 3.4E HTML tags (e.g. attribute and value-level enforcement)
- A suite of unit tests using `pytest`
- GitHub CI workflow for test suite

The end result is to try to build an OpenXiino that is a little more "production-grade", such that it could be run as a service for a small PalmOS community.

**Note that JavaScript of any type is still not supported.** The JavaScript implementation of Xiino is basically DHTML-level and is too small for the majority of reason to support JS today, which is for single-page applications written in major frameworks such as React. It's best to think of OpenXiino as a minimal translation layer on already relatively minimal pages. You can use it as a modern TLS-capable proxy to browse the now mostly-HTTPS web without having to worry about the obsolete SSL stack built into Xiino.

I'm maintaining this fork outside of nicl83/OpenXiino until it reaches some stability. After that, I'll ask the original maintainer if they're interested in upstreaming any of these changes.

## Usage

It is recommended to run this fork in the Docker image, which can be built from the `Dockerfile` in this repository. You'll need to provide the environment variables in `.env.sample` either by copying in a `.env` or by setting them in your `docker-compose.yml` or on the Docker command line.

## Development

If you're interested in working on this fork, fork it yourself. You'll want to run it outside the repository. To run the server for the first time, create a virtual environment, install dependencies, and execute it:

```bash
python3 -m venv venv && \
source venv/bin/activate && \
pip install -r requirements.txt && \
python3 dataserver.py
```

Tests are run using `pytest`:

```bash
python3 -m pytest tests/
```

## License

nicl83's original code is licensed under the more-permissive MIT license; this fork is licensed under the [GNU Affero General Public License 3.0](./LICENSE).
