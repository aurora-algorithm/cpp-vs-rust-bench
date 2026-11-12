//! Shared by the Rust programs: the totals line (byte for byte the same as cpp/src/common.hpp) and the progress
//! marks for the race chart.

use std::fs::File;
use std::io::{BufWriter, Write};
use std::time::Instant;

#[derive(Default)]
pub struct Totals {
    pub lines: u64,
    pub status_sum: u64,
    pub bytes: u64,
    pub text_len: u64,
    pub duration: f64,
}

impl Totals {
    pub fn add(&mut self, status: i64, bytes: u64, duration: f64, text: usize) {
        self.lines += 1;
        self.status_sum += status as u64;
        self.bytes += bytes;
        self.text_len += text as u64;
        self.duration += duration;
    }

    pub fn write(&self, path: &str) -> std::io::Result<()> {
        let mut out = BufWriter::new(File::create(path)?);
        let t = self;
        writeln!(out, "{}\t{}\t{}\t{}\t{:.6}", t.lines, t.status_sum, t.bytes, t.text_len, t.duration)?;
        out.flush()
    }
}

/// The time since start every 65,536 lines, written only when PROGRESS_OUT is set. Same work per line as the
/// C++ side: one increment and one compare.
pub struct Progress {
    start: Instant,
    lines: u64,
    marks: Vec<f64>,
}

impl Progress {
    pub fn new() -> Self {
        Self { start: Instant::now(), lines: 0, marks: Vec::new() }
    }

    #[inline]
    pub fn tick(&mut self) {
        self.lines += 1;
        if self.lines & 0xFFFF == 0 {
            self.marks.push(self.start.elapsed().as_secs_f64());
        }
    }
}

impl Default for Progress {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for Progress {
    fn drop(&mut self) {
        let Ok(path) = std::env::var("PROGRESS_OUT") else { return };
        let write = || -> std::io::Result<()> {
            let mut out = BufWriter::new(File::create(&path)?);
            for (i, t) in self.marks.iter().enumerate() {
                writeln!(out, "{}\t{:.6}", (i as u64 + 1) * 65536, t)?;
            }
            writeln!(out, "{}\t{:.6}", self.lines, self.start.elapsed().as_secs_f64())?;
            out.flush()
        };
        if let Err(e) = write() {
            eprintln!("cannot write {path}: {e}");
        }
    }
}

pub fn two_args(usage: &str) -> Result<(String, String), String> {
    let a: Vec<String> = std::env::args().skip(1).collect();
    match a.as_slice() {
        [input, output] => Ok((input.clone(), output.clone())),
        _ => Err(usage.to_string()),
    }
}
