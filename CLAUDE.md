# The Profit Clinic

**Site:** theprofitclinic.ai
**Repo:** github.com/namastan/theprofitclinic
**Hosting:** Vercel

## Stack

- Next.js 14 with App Router
- PostgreSQL via Drizzle ORM

## SEO Content Pages

- 61 SEO content pages stored in the database
- Served via `app/[...slug]/page.tsx`
- Content lives in the `pages` table with columns:
  - `slug`
  - `url`
  - `title`
  - `meta_title`
  - `meta_description`
  - `content_markdown`
  - `content_html`
  - `published`

## Known Issues

- **React 19 / Next.js 14 peer dependency conflict** blocking new Vercel deployments
  - Fix: upgrade to Next.js 15
