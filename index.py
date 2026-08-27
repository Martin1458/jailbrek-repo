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
import pathlib
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


HEAD = """<title>{{LABEL}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Chivo:wght@700;900&family=JetBrains+Mono:wght@400;700&family=Public+Sans:wght@400;500;600&display=swap">
<style>
  /* Neutrals carry a violet bias taken from the repo mark, so greys read as
     chosen rather than defaulted. Light palette lives on bare :root; the dark
     blocks only redefine tokens, never component colours. */
  :root {
    --paper: #FCFBFD;  --ink: #17151F;   --surface: #F3F1F7;
    --line: #E2DEEC;   --muted: #6B6579; --accent: #5B4BE0;
    --accent-ink: #FFFFFF;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --paper: #131017;  --ink: #ECEAF2;   --surface: #1D1A25;
      --line: #2E2A3A;   --muted: #9A93AC; --accent: #9B8CFF;
      --accent-ink: #131017;
    }
  }
  :root[data-theme="dark"] {
    --paper: #131017;  --ink: #ECEAF2;   --surface: #1D1A25;
    --line: #2E2A3A;   --muted: #9A93AC; --accent: #9B8CFF;
    --accent-ink: #131017;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0; padding: clamp(2rem, 7vw, 4.5rem) 1.25rem 4rem;
    background: var(--paper); color: var(--ink);
    font: 400 16px/1.65 "Public Sans", -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  main { max-width: 40rem; margin: 0 auto; display: flex; flex-direction: column; gap: 3rem; }

  .masthead { display: flex; align-items: center; gap: 1rem; }
  .masthead img { width: 60px; height: 60px; border-radius: 14px; flex-shrink: 0; }
  .wordmark {
    font-family: Chivo, sans-serif; font-weight: 900;
    font-size: clamp(1.6rem, 6vw, 2.1rem); line-height: 1.05;
    letter-spacing: -.035em; margin: 0; text-wrap: balance;
  }
  .tagline { color: var(--muted); margin: .2rem 0 0; font-size: .95rem; }

  section { display: flex; flex-direction: column; gap: 1rem; }
  h2 {
    font-family: Chivo, sans-serif; font-weight: 700; font-size: .78rem;
    text-transform: uppercase; letter-spacing: .1em; color: var(--muted);
    margin: 0; padding-bottom: .6rem; border-bottom: 1px solid var(--line);
  }

  /* The URL is the one thing every visitor came for, so it gets the weight. */
  .source { display: flex; gap: .5rem; align-items: stretch; flex-wrap: wrap; }
  .source code {
    flex: 1 1 16rem; min-width: 0;
    font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
    font-size: .88rem; line-height: 1.5; word-break: break-all;
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 10px; padding: .8rem .9rem;
  }
  .copy {
    flex: 0 0 auto; font: 600 .88rem/1 "Public Sans", sans-serif;
    background: var(--accent); color: var(--accent-ink); border: 0;
    border-radius: 10px; padding: 0 1.15rem; cursor: pointer;
    transition: opacity .15s ease;
  }
  .copy:hover { opacity: .85; }
  .copy:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  ol { margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: .35rem; }
  ol::marker, li::marker { color: var(--muted); }
  .note { color: var(--muted); font-size: .92rem; margin: 0; }

  /* Rows, not cards: this page is a package index and should read like one. */
  .tweak {
    display: grid; grid-template-columns: 56px 1fr; gap: 1rem;
    padding: 1.15rem 0; border-bottom: 1px solid var(--line);
  }
  .tweak:first-of-type { border-top: 1px solid var(--line); }
  .tweak img, .tweak .noicon { width: 56px; height: 56px; border-radius: 13px; }
  .tweak .noicon { background: var(--surface); border: 1px solid var(--line); }
  .tweak .body { min-width: 0; display: flex; flex-direction: column; gap: .45rem; }
  .tweak h3 {
    font-family: Chivo, sans-serif; font-weight: 700; font-size: 1.08rem;
    letter-spacing: -.015em; margin: 0;
  }
  .tweak .summary { margin: 0; }
  .tweak .long { margin: 0; color: var(--muted); font-size: .93rem; }
  .facts {
    font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
    font-size: .76rem; color: var(--muted); font-variant-numeric: tabular-nums;
    display: flex; flex-wrap: wrap; gap: .5rem; margin: .1rem 0 0;
  }
  .facts span::after { content: " ·"; opacity: .5; }
  .facts span:last-child::after { content: ""; }
  .tweak a { color: var(--accent); font-weight: 500; font-size: .93rem; text-decoration: none; }
  .tweak a:hover { text-decoration: underline; }

  footer { color: var(--muted); font-size: .85rem; border-top: 1px solid var(--line); padding-top: 1.25rem; }
  footer p { margin: 0 0 .4rem; }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>"""

BODY = """<main>
  <header class="masthead">
    <img src="CydiaIcon.png" alt="">
    <div>
      <h1 class="wordmark">{{LABEL}}</h1>
      <p class="tagline">{{DESCRIPTION}}</p>
    </div>
  </header>

  <section>
    <h2>Add this source</h2>
    <div class="source">
      <code id="repo-url">{{REPO_URL}}</code>
      <button class="copy" id="copy">Copy</button>
    </div>
    <ol>
      <li>Open Sileo, Zebra, or Cydia and go to <strong>Sources</strong>.</li>
      <li>Tap <strong>+</strong> and paste the address.</li>
      <li>Install anything below.</li>
    </ol>
    <p class="note">Needs a rootless jailbreak on iOS 15 or later.
       Built and tested on iOS 17.0.2 with Dopamine.</p>
  </section>

  <section>
    <h2>{{COUNT_LABEL}}</h2>
{{CARDS}}
  </section>

  <footer>
    <p>Packages are unsigned, so your package manager may warn you before installing.</p>
    <p>If a tweak does not take effect, respring.</p>
  </footer>
</main>
<script>
  document.getElementById("copy").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    try {
      await navigator.clipboard.writeText(document.getElementById("repo-url").textContent.trim());
      btn.textContent = "Copied";
    } catch {
      btn.textContent = "Select it";
    }
    setTimeout(() => { btn.textContent = "Copy"; }, 1800);
  });
</script>"""


def human_size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


def render_cards(latest: list) -> str:
    cards = []
    for fields, deb in latest:
        summary, body = split_description(fields.get("Description", ""))
        icon = fields.get("Icon", "")
        # Icon: is an absolute URL for package managers, but the page sits at that
        # same origin, so a relative path also works in a local preview.
        if icon.startswith(REPO_URL):
            icon = icon[len(REPO_URL):]
        icon_html = (f'<img src="{html.escape(icon)}" alt="">' if icon
                     else '<div class="noicon"></div>')
        paras = "".join(f'<p class="long">{html.escape(p)}</p>'
                        for p in body.split("\n\n") if p.strip())
        facts = " ".join(f"<span>{html.escape(v)}</span>" for v in [
            fields["Package"],
            human_size(deb.stat().st_size),
            fields.get("Architecture", ""),
        ] if v)
        cards.append(f"""    <article class="tweak">
      {icon_html}
      <div class="body">
        <h3>{html.escape(fields.get("Name", fields["Package"]))} {html.escape(fields.get("Version", ""))}</h3>
        <p class="summary">{html.escape(summary)}</p>
        {paras}
        <p class="facts">{facts}</p>
        <p><a href="debs/{html.escape(deb.name)}">Download .deb</a></p>
      </div>
    </article>""")
    return "\n".join(cards) if cards else "    <p class=\"note\">Nothing published yet.</p>"


def render(latest: list):
    """Returns (head, body). The head carries <title> and styles; the body is the
    page content. Kept separate so the same markup can be emitted either as a
    standalone document or as a fragment for previewing."""
    count = len(latest)
    subs = {
        "{{LABEL}}": html.escape(LABEL),
        "{{DESCRIPTION}}": html.escape(DESCRIPTION),
        "{{REPO_URL}}": html.escape(REPO_URL),
        "{{COUNT_LABEL}}": f"{count} tweak" + ("" if count == 1 else "s"),
        "{{CARDS}}": render_cards(latest),
    }
    head, body = HEAD, BODY
    for k, v in subs.items():
        head = head.replace(k, v)
        body = body.replace(k, v)
    return head, body


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
    head, body = render(latest)
    (DOCS / "index.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        + head + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n"
    )

    # Artifact previews are published as a fragment: the host supplies the
    # document wrapper, so emitting our own would nest one page inside another.
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        pathlib.Path(sys.argv[2]).write_text(head + "\n" + body + "\n")
        print(f"preview -> {sys.argv[2]}")

    print(f"\n{len(debs)} deb(s), {len(latest)} package(s) -> docs/")
    print("Packages, Packages.gz, Release, index.html")


if __name__ == "__main__":
    main()
