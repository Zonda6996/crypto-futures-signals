import { createReadStream, statSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { put } from '@vercel/blob'

const archive = process.argv[2]
if (!archive) throw new Error('usage: node scripts/publish_altcoin_multitf_004.mjs <archive.tar.gz>')

const hash = createHash('sha256')
for await (const chunk of createReadStream(archive)) hash.update(chunk)
const sha256 = hash.digest('hex')
const size = statSync(archive).size
const pathname = `altcoin-multitf-004/${sha256}.tar.gz`
const blob = await put(pathname, createReadStream(archive), {
  access: 'public',
  addRandomSuffix: false,
  multipart: true,
  contentType: 'application/gzip',
})
console.log(JSON.stringify({
  protocol_id: 'ALT-MULTITF-004',
  url: blob.url,
  pathname: blob.pathname,
  sha256,
  size,
}, null, 2))
