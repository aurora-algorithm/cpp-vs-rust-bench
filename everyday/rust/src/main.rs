//! Everyday jobs on the same log, Rust side. Byte for byte the same output as ../cpp/src/everyday.cpp.
//! usage: everyday regex|sort|agg INPUT OUTPUT OPTION
//!   regex reads the raw JSON-lines log; sort and agg read records.bin (tools/records.py).
//! Loading the input (reading the file, building the records) is timed apart from the job. Both times go to the
//! file named by BENCH_TIMES, one JSON line per run, because hyperfine discards the program's stdout. The output is
//! a digest (count + FNV-1a), so writing it costs next to nothing inside hyperfine's wall time.

use std::collections::HashMap;
use std::error::Error;
use std::fs::OpenOptions;
use std::io::Write;
use std::time::Instant;

use rayon::prelude::*;

/// 5xx responses on /api/<collection>/<id> routes; the capture is the path.
const PATTERN: &str = r#""path":"(/api/[a-z]+/[0-9]+)","status":5[0-9][0-9]"#;

type Res<T> = Result<T, Box<dyn Error>>;

// status and bytes are read so loading costs the same as the C++ side; no job uses them.
struct Record {
    path: String,
    duration: f64,
    #[allow(dead_code)]
    status: u16,
    #[allow(dead_code)]
    bytes: u64,
}

#[derive(Default)]
struct Times {
    load_s: f64,
    job_s: f64,
}

struct Fnv(u64);

impl Fnv {
    fn new() -> Self {
        Fnv(0xcbf2_9ce4_8422_2325)
    }
    fn add(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.0 = (self.0 ^ b as u64).wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    fn add_f64(&mut self, x: f64) {
        self.add(&x.to_bits().to_le_bytes());
    }
    fn line(&self, count: usize) -> String {
        format!("{count}\t{}\n", self.0)
    }
}

fn take<const N: usize>(d: &[u8], at: &mut usize) -> Res<[u8; N]> {
    let b = d.get(*at..*at + N).ok_or("records.bin is truncated")?;
    *at += N;
    Ok(b.try_into()?)
}

/// records.bin: per record f64 duration, u16 status, u64 bytes, u16 path length, path bytes (little endian).
fn parse_records(d: &[u8]) -> Res<Vec<Record>> {
    let mut out = Vec::new();
    let mut at = 0;
    while at < d.len() {
        let duration = f64::from_le_bytes(take(d, &mut at)?);
        let status = u16::from_le_bytes(take(d, &mut at)?);
        let bytes = u64::from_le_bytes(take(d, &mut at)?);
        let len = u16::from_le_bytes(take(d, &mut at)?) as usize;
        let raw = d.get(at..at + len).ok_or("records.bin is truncated")?;
        at += len;
        out.push(Record {
            path: String::from_utf8(raw.to_vec())?,
            duration,
            status,
            bytes,
        });
    }
    Ok(out)
}

fn regex_lines(text: &str) -> Vec<(usize, &[u8])> {
    let re = regex::Regex::new(PATTERN).unwrap();
    let mut found = Vec::new();
    let mut offset = 0;
    for line in text.split('\n') {
        if let Some(caps) = re.captures(line) {
            let path = caps.get(1).unwrap();
            found.push((offset + path.start(), path.as_str().as_bytes()));
        }
        offset += line.len() + 1;
    }
    found
}

/// Count + p99 duration per path: Rayon folds a map per piece of work, merges them, then the p99s in parallel.
fn agg(records: &[Record]) -> Vec<(&str, usize, f64)> {
    let groups: HashMap<&str, Vec<f64>> = records
        .par_iter()
        .fold(HashMap::new, |mut m: HashMap<&str, Vec<f64>>, r| {
            m.entry(&r.path).or_default().push(r.duration);
            m
        })
        .reduce(HashMap::new, |mut a, b| {
            for (k, mut v) in b {
                a.entry(k).or_default().append(&mut v);
            }
            a
        });
    groups
        .into_par_iter()
        .map(|(path, mut d)| {
            let i = (d.len() - 1) * 99 / 100;
            let p99 = *d.select_nth_unstable_by(i, f64::total_cmp).1;
            (path, d.len(), p99)
        })
        .collect()
}

fn durations_digest(recs: &[Record]) -> String {
    let mut f = Fnv::new();
    for r in recs {
        f.add_f64(r.duration);
    }
    f.line(recs.len())
}

fn regex_job(option: &str, data: &[u8], t: &mut Times) -> Res<String> {
    let start = Instant::now();
    let found = match option {
        "lines" => regex_lines(std::str::from_utf8(data)?),
        _ => return Err(format!("unknown regex option {option}").into()),
    };
    t.job_s = start.elapsed().as_secs_f64();
    let mut f = Fnv::new();
    for (off, path) in &found {
        f.add(&(*off as u64).to_le_bytes());
        f.add(path);
    }
    Ok(f.line(found.len()))
}

fn records_job(mode: &str, option: &str, mut recs: Vec<Record>, t: &mut Times) -> Res<String> {
    match (mode, option) {
        ("sort", "duration") => {
            let start = Instant::now();
            recs.sort_unstable_by(|a, b| a.duration.total_cmp(&b.duration));
            t.job_s = start.elapsed().as_secs_f64();
            Ok(durations_digest(&recs))
        }
        ("agg", "par") => {
            let start = Instant::now();
            let mut rows = agg(&recs);
            t.job_s = start.elapsed().as_secs_f64();
            rows.sort_unstable_by(|a, b| a.0.cmp(b.0));
            Ok(rows
                .iter()
                .map(|(path, n, p99)| format!("{path}\t{n}\t{p99:.6}\n"))
                .collect())
        }
        _ => Err(format!("unknown mode/option {mode} {option}").into()),
    }
}

fn append_times(t: &Times) -> Res<()> {
    if let Ok(path) = std::env::var("BENCH_TIMES") {
        let mut f = OpenOptions::new().create(true).append(true).open(path)?;
        writeln!(
            f,
            "{{\"load_s\": {:.6}, \"job_s\": {:.6}}}",
            t.load_s, t.job_s
        )?;
    }
    Ok(())
}

fn main() -> Res<()> {
    let a: Vec<String> = std::env::args().collect();
    if a.len() != 5 {
        return Err("usage: everyday regex|sort|agg INPUT OUTPUT OPTION".into());
    }
    let (mode, input, output, option) = (a[1].as_str(), &a[2], &a[3], a[4].as_str());
    let mut t = Times::default();
    let start = Instant::now();
    let data = std::fs::read(input)?;
    let out = if mode == "regex" {
        t.load_s = start.elapsed().as_secs_f64();
        regex_job(option, &data, &mut t)?
    } else {
        let recs = parse_records(&data)?;
        drop(data);
        t.load_s = start.elapsed().as_secs_f64();
        records_job(mode, option, recs, &mut t)?
    };
    std::fs::write(output, out)?;
    append_times(&t)?;
    println!(
        "{{\"load_s\": {:.6}, \"job_s\": {:.6}, \"threads\": {}}}",
        t.load_s,
        t.job_s,
        rayon::current_num_threads()
    );
    Ok(())
}
