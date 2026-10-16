# Python 3.12 Linux dependency evidence

The adjacent requirements file locks the requested hosted-CI dependency
scope: CPython 3.12, x86_64, `manylinux_2_28`, and the `full`, `dev`, and
`jax` extras. It excludes the BNG3 source package itself so the lock covers
third-party packages only. The current workflows' per-job install commands
remain separate; this artifact records the requested combined dependency set.
Lock SHA-256: `e952cd2d30cddf9c8ec506b34e5d3f168eb3543abc828211a0a9cfa6cf572322`.

## Resolution and wheel hashes

The file was generated with uv 0.12.20 using this target-aware command:

```sh
uv pip compile pyproject.toml \
  --extra full --extra dev --extra jax \
  --no-emit-package bionetgen \
  --python-version 3.12 \
  --python-platform x86_64-manylinux_2_28 \
  --generate-hashes --only-binary :all:
```

I reran that resolution with uv 0.12.20 on macOS and compared the result with
the lock. All 35 package pins and hash lines were byte-identical. This is a
target-specific resolution; it is not a freeze of the host Python environment.

I then downloaded the selected wheels using pip 26.2.1 with explicit CPython
and manylinux target options and hash enforcement:

```sh
python3 -m pip download --require-hashes --only-binary=:all: \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_27_x86_64 \
  --platform manylinux_2_26_x86_64 --platform manylinux_2_25_x86_64 \
  --platform manylinux_2_24_x86_64 --platform manylinux_2_23_x86_64 \
  --platform manylinux_2_22_x86_64 --platform manylinux_2_21_x86_64 \
  --platform manylinux_2_20_x86_64 --platform manylinux_2_19_x86_64 \
  --platform manylinux_2_18_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux2014_x86_64 --platform manylinux_2_12_x86_64 \
  --platform manylinux2010_x86_64 --platform manylinux_2_5_x86_64 \
  --platform manylinux1_x86_64 --python-version 3.12 \
  --implementation cp --abi cp312 \
  --dest /private/tmp/bng3-issue179-download \
  -r provenance/dependencies/python-3.12-linux-x86_64-manylinux_2_28-full-dev-jax.txt
```

pip's `--platform manylinux_2_28_x86_64` alone does not include older
compatible manylinux tags, which excluded jaxlib on the first attempt. With
the full compatibility tag list, all 35 locked wheels (197 MB) downloaded.
Recomputed SHA-256 digests matched the lock for all 35; there were no missing
or unlisted packages.

The download and hash check validates package resolution, availability, wheel
metadata selection, and artifact hashes. This Mac host is Apple Silicon and
cannot execute Linux wheels. Docker, Podman, and Skopeo were unavailable, so no
Linux wheel or compiler image was run here.

## manylinux compiler image

The CI and release workflows set `CIBW_MANYLINUX_X86_64_IMAGE: manylinux_2_28`
and install `cibuildwheel==4.2.1`. In the official [cibuildwheel v4.2.1 pinned
image table](https://github.com/pypa/cibuildwheel/blob/v4.2.1/cibuildwheel/resources/pinned_docker_images.cfg),
that value maps to:

```text
quay.io/pypa/manylinux_2_28_x86_64@sha256:53390351aeb4688114b02c36a23b3e6ce1166ee9b7afc5df1a4f776354fc764c
```

The table labels this image `2026.09.05-1`. A read-only Quay registry request
for that tag returned HTTP 200 and `Docker-Content-Digest:
sha256:53390351aeb4688114b02c36a23b3e6ce1166ee9b7afc5df1a4f776354fc764c` on
2026-10-08 13:03:50 UTC. I also fetched the manifest body and independently
computed the same SHA-256. This confirms the immutable image reference and
registry metadata; it does not claim that the image was executed.

## Method references

- [uv pip compile documentation](https://docs.astral.sh/uv/pip/compile/)
- [pip download documentation](https://pip.pypa.io/en/stable/cli/pip_download/)
- [cibuildwheel v4.2.1 pinned image table](https://github.com/pypa/cibuildwheel/blob/v4.2.1/cibuildwheel/resources/pinned_docker_images.cfg)
- [Quay manifest endpoint for the verified tag](https://quay.io/v2/pypa/manylinux_2_28_x86_64/manifests/2026.09.05-1)
