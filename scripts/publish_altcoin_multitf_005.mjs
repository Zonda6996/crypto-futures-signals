import { createReadStream, statSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { list, put } from '@vercel/blob'

const [archive, output = '.alt-multitf-005/release/blob-result.json'] = process.argv.slice(2)
if (!archive) throw new Error('usage: node scripts/publish_altcoin_multitf_005.mjs <archive.tar.gz> [result.json]')
if (!process.env.BLOB_READ_WRITE_TOKEN) throw new Error('BLOB_READ_WRITE_TOKEN is required')

const digest = createHash('sha256')
for await (const chunk of createReadStream(archive)) digest.update(chunk)
const sha256 = digest.digest('hex')
const size = statSync(archive).size
const pathname = `altcoin-multitf-005/${sha256}.tar.gz`
const existing = (await list({ prefix: pathname, limit: 10, token: process.env.BLOB_READ_WRITE_TOKEN })).blobs.find((blob) => blob.pathname === pathname)
const blob = existing ?? await put(pathname, createReadStream(archive), {
  access: 'public', addRandomSuffix: false, multipart: true, contentType: 'application/gzip', token: process.env.BLOB_READ_WRITE_TOKEN,
})
if (blob.size !== size) throw new Error(`Blob size mismatch: ${blob.size} != ${size}`)
const result = { protocol_id: 'ALT-MULTITF-005', access: 'public', url: blob.url, pathname: blob.pathname, sha256, size }
writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600 })
console.log(JSON.stringify({ ...result, url: '[written to release metadata]' }, null, 2))
