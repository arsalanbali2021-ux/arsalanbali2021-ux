# How this profile keeps itself up to date

The profile README rebuilds itself. You shouldn't need to edit it when you add a repo.

## What happens automatically

A GitHub Action (`.github/workflows/refresh-profile.yml`) runs every 6 hours, on every push to `main`, and whenever you start it by hand. It runs `scripts/build_profile.py`, which reads live data from the GitHub API and rewrites:

| Part of the profile | Where the data comes from |
| --- | --- |
| Header line chart and total | Your contribution calendar for the last 12 months |
| Work cards | Your public, non-fork repos, newest push first, after anything in `featured` |
| Card descriptions | The repo's description. If it has fewer than 4 words, the first sentence of its README |
| Card titles | The README's `# Heading` when it matches the repo name (for example `ValueTrack`), otherwise the repo name |
| Heading into AI/ML list | Public repos whose topics, name or description mention machine learning (or that are Jupyter notebooks), plus ML forks you are studying from |
| Languages bar | Language bytes across your public, non-fork repos |
| Timeline | Each public repo from creation to last push, featured private repos from their `started` date, and ML forks as study markers |
| Elsewhere links | Website, social accounts and public email from your GitHub profile settings |

When nothing has changed, the Action doesn't commit anything.

## Things you might want to change

- **Make a new repo show up well:** give it a one-line description, and add the `machine-learning` topic if it is an ML project. It appears on the next run.
- **Change the intro or toolkit text:** edit `README.md`, but only outside the `<!-- NAME:START -->` / `<!-- NAME:END -->` markers.
- **Change the header text, card limit or ML keywords:** edit `profile.json`.
- **Hide a repo:** add its name to `"exclude"` in `profile.json`.
- **Feature a repo first:** add it to `"featured"` in `profile.json`. Private repos can only be featured this way, and only the text you write there is shown.
- **Script Atlas goes public:** nothing to do. The card switches to live data and drops the `PRIVATE` tag.
- **Add LinkedIn or a website:** add it in GitHub under Settings → Profile → Social accounts. It appears under *Elsewhere*.

## Run it now

```bash
gh workflow run refresh-profile.yml
```

To preview locally (Python 3.9 or later, no packages needed):

```bash
GITHUB_TOKEN=$(gh auth token) python scripts/build_profile.py
```

GitHub pauses scheduled workflows in a public repo after 60 days with no activity. The header chart and timeline change daily, which normally keeps it active. If GitHub ever emails you that the workflow was disabled, open the Actions tab and click **Enable workflow**.
