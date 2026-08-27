#!/usr/bin/env python3
"""Index every .deb in docs/debs/ into an APT repo, and rebuild the landing page.

    ./index.py

Adding a tweak is a file drop: put its .deb in docs/debs/, optionally put a
128x128 PNG in docs/icons/ and point the package's `Icon:` field at it, then run
this. Nothing here is per-tweak.

Keep old .deb files around. Each version gets its own stanza, package managers
install the highest, and anyone who wants an older build can still fetch it.

No dpkg on macOS, so the control file is pulled out of the ar archive by hand
rather than with dpkg-scanpackages.
"""

import gzip
import hashlib
import html
import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DEBS = DOCS / "debs"

REPO_URL = "https://martin1458.github.io/jailbrek-repo/"
ORIGIN = "jailbrek"
LABEL = "Martin's Tweaks"
DESCRIPTION = "Tweaks for iOS 17"


def control_of(deb: Path) -> str:
    """Pull the control file out of a .deb without dpkg."""
    members = subprocess.run(
        ["ar", "t", str(deb)], capture_output=True, text=True, check=True
    ).stdout.split()
    name = next((m for m in members if m.startswith("control.tar")), None)
    if not name:
        sys.exit(f"no control.tar member in {deb.name}: {members}")

    blob = subprocess.run(
        ["ar", "p", str(deb), name], capture_output=True, check=True
    ).stdout

    if name.endswith((".lzma", ".xz")):
        import lzma

        blob, mode = lzma.decompress(blob), "r:"
    elif name.endswith(".gz"):
        mode = "r:gz"
    else:
        mode = "r:"

    with tarfile.open(fileobj=io.BytesIO(blob), mode=mode) as tf:
        entry = next(m for m in tf.getmembers() if Path(m.name).name == "control")
        return tf.extractfile(entry).read().decode().strip()


def parse_control(text: str) -> dict:
    """Debian control format: continuation lines are indented and belong to the
    field above them."""
    fields, key = {}, None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t" and key:
            fields[key] += "\n" + line.strip()
        else:
            k, _, v = line.partition(":")
            key = k.strip()
            fields[key] = v.strip()
    return fields


def version_key(v: str):
    """Good enough ordering for semver-ish versions: compare number runs
    numerically and everything else as text."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", v)]


def hashes(data: bytes) -> dict:
    return {
        "MD5sum": hashlib.md5(data).hexdigest(),
        "SHA1": hashlib.sha1(data).hexdigest(),
        "SHA256": hashlib.sha256(data).hexdigest(),
    }


def split_description(desc: str):
    """First line is the summary; the rest is the body, where a lone '.' is a
    blank line."""
    lines = desc.split("\n")
    summary = lines[0]
    body = [("" if ln == "." else ln) for ln in lines[1:]]
    return summary, "\n".join(body).strip()


def render_page(latest: list) -> str:
    cards = []
    for fields, deb in latest:
        name = html.escape(fields.get("Name", fields["Package"]))
        version = html.escape(fields.get("Version", ""))
        summary, body = split_description(fields.get("Description", ""))
        icon = fields.get("Icon", "")
        # Icon: is an absolute URL for package managers, but the page sits at
        # that same origin, so relative works locally too (e.g. file:// preview).
        if icon.startswith(REPO_URL):
            icon = icon[len(REPO_URL):]
        icon_html = (
            f'<img class="icon" src="{html.escape(icon)}" alt="">'
            if icon
            else '<div class="icon placeholder"></div>'
        )
        paras = "".join(
            f"<p>{html.escape(p)}</p>" for p in body.split("\n\n") if p.strip()
        )
        cards.append(f"""    <article class="tweak">
      {icon_html}
      <div class="meta">
        <h3>{name} <span class="version">{version}</span></h3>
        <p class="summary">{html.escape(summary)}</p>
        {paras}
        <p class="dl"><a href="debs/{html.escape(deb.name)}">Download .deb</a></p>
      </div>
    </article>""")

    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(LABEL)}</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #1d1d1f; --muted: #6e6e73;
    --card: #f5f5f7; --line: #d2d2d7; --accent: #0071e3;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #1d1d1f; --fg: #f5f5f7; --muted: #a1a1a6;
      --card: #2c2c2e; --line: #3a3a3c; --accent: #2997ff;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 3rem 1.25rem 5rem;
    font: 16px/1.6 -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    background: var(--bg); color: var(--fg);
  }}
  main {{ max-width: 40rem; margin: 0 auto; }}
  header {{ display: flex; align-items: center; gap: 1rem; margin-bottom: .5rem; }}
  header img {{ width: 64px; height: 64px; border-radius: 14px; }}
  h1 {{ font-size: 1.75rem; margin: 0; letter-spacing: -.02em; }}
  .tagline {{ color: var(--muted); margin: .15rem 0 0; }}
  h2 {{ font-size: 1.05rem; margin: 2.5rem 0 .75rem; letter-spacing: -.01em; }}
  .url {{
    display: block; background: var(--card); border: 1px solid var(--line);
    padding: .85rem 1rem; border-radius: 10px; word-break: break-all;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9rem;
  }}
  ol {{ padding-left: 1.25rem; }}
  ol li {{ margin: .3rem 0; }}
  .tweak {{
    display: flex; gap: 1rem; background: var(--card);
    border: 1px solid var(--line); border-radius: 12px;
    padding: 1rem; margin-bottom: 1rem;
  }}
  .icon {{ width: 60px; height: 60px; border-radius: 13px; flex-shrink: 0; }}
  .placeholder {{ background: var(--line); }}
  .meta {{ min-width: 0; }}
  .meta h3 {{ margin: 0 0 .2rem; font-size: 1.05rem; }}
  .version {{ color: var(--muted); font-weight: 400; font-size: .85rem; }}
  .summary {{ margin: 0 0 .5rem; }}
  .meta p {{ margin: 0 0 .5rem; }}
  .meta p:not(.summary):not(.dl) {{ color: var(--muted); font-size: .92rem; }}
  .dl a {{ color: var(--accent); text-decoration: none; font-size: .92rem; }}
  .dl a:hover {{ text-decoration: underline; }}
  footer {{
    margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--line);
    color: var(--muted); font-size: .85rem;
  }}
</style>
<main>
  <header>
    <img src="CydiaIcon.png" alt="">
    <div>
      <h1>{html.escape(LABEL)}</h1>
      <p class="tagline">{html.escape(DESCRIPTION)}</p>
    </div>
  </header>

  <h2>Add this repo</h2>
  <code class="url">{html.escape(REPO_URL)}</code>
  <ol>
    <li>Open Sileo (or Zebra, or Cydia) and go to <strong>Sources</strong>.</li>
    <li>Tap <strong>+</strong> and paste the address above.</li>
    <li>Find the tweak below and install it.</li>
  </ol>
  <p>Everything here needs a <strong>rootless</strong> jailbreak on iOS 15 or
     later. Built and tested on iOS 17.0.2 with Dopamine.</p>

  <h2>Tweaks</h2>
{chr(10).join(cards) if cards else "  <p>Nothing published yet.</p>"}

  <footer>
    Respring after installing if a tweak does not take effect.
    Packages are unsigned; your package manager may warn about that.
  </footer>
</main>
</html>
"""


def main():
    debs = sorted(DEBS.glob("*.deb"))
    if not debs:
        sys.exit(f"no .deb files in {DEBS}")

    stanzas, by_package = [], {}
    for deb in debs:
        raw = control_of(deb)
        fields = parse_control(raw)
        data = deb.read_bytes()

        stanzas.append(
            raw
            + "\n"
            + "\n".join(
                [f"Filename: debs/{deb.name}", f"Size: {len(data)}"]
                + [f"{k}: {v}" for k, v in hashes(data).items()]
            )
        )

        pkg = fields["Package"]
        best = by_package.get(pkg)
        if not best or version_key(fields["Version"]) > version_key(best[0]["Version"]):
            by_package[pkg] = (fields, deb)

        print(f"  {pkg} {fields['Version']} ({len(data):,} bytes)")

    packages = ("\n\n".join(stanzas) + "\n").encode()
    (DOCS / "Packages").write_bytes(packages)
    # mtime=0 so the gzip is reproducible when nothing actually changed.
    gz = gzip.compress(packages, mtime=0)
    (DOCS / "Packages.gz").write_bytes(gz)

    (DOCS / "Release").write_text(
        "\n".join([
            f"Origin: {ORIGIN}",
            f"Label: {LABEL}",
            "Suite: stable",
            "Version: 1.0",
            "Codename: ios",
            "Architectures: iphoneos-arm64",
            "Components: main",
            f"Description: {DESCRIPTION}",
            "MD5Sum:",
            f" {hashes(packages)['MD5sum']} {len(packages)} Packages",
            f" {hashes(gz)['MD5sum']} {len(gz)} Packages.gz",
            "SHA256:",
            f" {hashes(packages)['SHA256']} {len(packages)} Packages",
            f" {hashes(gz)['SHA256']} {len(gz)} Packages.gz",
            "",
        ])
    )

    latest = [by_package[p] for p in sorted(by_package)]
    (DOCS / "index.html").write_text(render_page(latest))

    print(f"\n{len(debs)} deb(s), {len(latest)} package(s) -> docs/")
    print("Packages, Packages.gz, Release, index.html")


if __name__ == "__main__":
    main()
