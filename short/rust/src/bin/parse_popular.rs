//! Test 1, Rust: the most used JSON library (serde_json), one line at a time, into a struct.

use std::error::Error;
use std::fs::File;
use std::io::{BufRead, BufReader};

use cpp_vs_rust_short::{Progress, Totals, two_args};
use serde::Deserialize;

#[derive(Deserialize)]
struct Record {
    ts: String,
    method: String,
    path: String,
    status: i64,
    bytes: u64,
    duration: f64,
}

fn main() -> Result<(), Box<dyn Error>> {
    let (input, output) = two_args("usage: parse_popular INPUT.jsonl OUTPUT.tsv")?;
    let mut progress = Progress::new();
    let reader = BufReader::new(File::open(&input)?);
    let mut t = Totals::default();
    for line in reader.lines() {
        let r: Record = serde_json::from_str(&line?)?;
        t.add(r.status, r.bytes, r.duration, r.ts.len() + r.method.len() + r.path.len());
        progress.tick();
    }
    t.write(&output)?;
    Ok(())
}
