//! Test 2, Rust: the whole file in memory, parsed with one of three crates. "serde" streams serde_json over the
//! whole buffer with borrowed strings; "simd" is simd-json (one set of buffers reused for every line); "sonic" is
//! sonic-rs's stream. The session runs all three and the video uses the fastest.

use std::error::Error;

use cpp_vs_rust_short::{Progress, Totals};
use serde::Deserialize;

#[derive(Deserialize)]
struct Row<'a> {
    #[serde(borrow)]
    ts: &'a str,
    #[serde(borrow)]
    method: &'a str,
    #[serde(borrow)]
    path: &'a str,
    status: i64,
    bytes: u64,
    duration: f64,
}

fn add(t: &mut Totals, r: &Row) {
    t.add(r.status, r.bytes, r.duration, r.ts.len() + r.method.len() + r.path.len());
}

fn main() -> Result<(), Box<dyn Error>> {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let [input, output, crate_name] = a.as_slice() else {
        return Err("usage: parse_fastest INPUT.jsonl OUTPUT.tsv serde|simd|sonic".into());
    };
    let mut progress = Progress::new();
    let mut data = std::fs::read(input)?;
    let mut t = Totals::default();
    match crate_name.as_str() {
        "serde" => {
            for row in serde_json::Deserializer::from_slice(&data).into_iter::<Row>() {
                add(&mut t, &row?);
                progress.tick();
            }
        }
        "sonic" => {
            // sonic-rs 0.5's stream ends with an EOF error at the trailing newline instead of None.
            for row in sonic_rs::Deserializer::from_slice(&data).into_stream::<Row>() {
                match row {
                    Ok(row) => {
                        add(&mut t, &row);
                        progress.tick();
                    }
                    Err(e) if e.is_eof() && data[e.offset().min(data.len())..].iter().all(u8::is_ascii_whitespace) => break,
                    Err(e) => return Err(e.into()),
                }
            }
        }
        "simd" => {
            let mut buffers = simd_json::Buffers::new(4096);
            let mut start = 0;
            while let Some(len) = memchr::memchr(b'\n', &data[start..]) {
                let end = start + len;
                let row: Row = simd_json::serde::from_slice_with_buffers(&mut data[start..end], &mut buffers)?;
                add(&mut t, &row);
                progress.tick();
                start = end + 1;
            }
        }
        _ => return Err("unknown crate: serde|simd|sonic".into()),
    }
    t.write(output)?;
    Ok(())
}
