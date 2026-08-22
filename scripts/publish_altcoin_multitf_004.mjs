import { createReadStream, statSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { list, put } from '@vercel/blob'

const archive = process.argv[2]
if (!archive) throw new Error('usage: node scripts/publish_altcoin_multitf_004.mjs <archive.tar.gz>')

const hash = createHash('sha256')
for await (const chunk of createReadStream(archive)) hash.update(chunk)
const sha256 = hash.digest('hex')
const size = statSync(archive).size
const pathname = `altcoin-multitf-004/${sha256}.tar.gz`
const existing = (await list({ prefix: pathname, limit: 1 })).blobs.find(
  (candidate) => candidate.pathname === pathname,
)
const blob = existing ?? await put(pathname, createReadStream(archive), {
  access: 'private',
  addRandomSuffix: false,
  multipart: true,
  contentType: 'application/gzip',
})
if (blob.size !== size) throw new Error(`existing Blob size mismatch: ${blob.size} != ${size}`)
console.log(JSON.stringify({
  protocol_id: 'ALT-MULTITF-004',
  url: blob.url,
  pathname: blob.pathname,
  sha256,
  size,
}, null, 2))
