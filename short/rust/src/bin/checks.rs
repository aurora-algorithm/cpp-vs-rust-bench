//! Test 3, Rust: add up every request duration in a scrambled order, so the compiler can't prove an index is in
//! range. "index" is v[i] (Rust checks every index), "unchecked" is get_unchecked (no check, needs unsafe).

use std::error::Error;
use std::io::Write;

const PASSES: usize = 40;

fn main() -> Result<(), Box<dyn Error>> {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let [input, output, how] = a.as_slice() else {
        return Err("usage: checks DURATIONS.bin OUTPUT.txt index|unchecked".into());
    };
    let bytes = std::fs::read(input)?;
    let v: Vec<f64> = bytes.chunks_exact(8).map(|b| f64::from_le_bytes(b.try_into().unwrap())).collect();
    let n = v.len();
    let idx: Vec<usize> = (0..n as u64).map(|i| (i * 2_654_435_761 % n as u64) as usize).collect();
    let mut sum = 0.0;
    match how.as_str() {
        "index" => {
            for _ in 0..PASSES {
                for &i in &idx {
                    sum += v[i];
                }
            }
        }
        "unchecked" => {
            for _ in 0..PASSES {
                for &i in &idx {
                    // SAFETY: every idx entry is i * k % n, below n = v.len().
                    sum += unsafe { *v.get_unchecked(i) };
                }
            }
        }
        _ => return Err("unknown option: index|unchecked".into()),
    }
    writeln!(std::fs::File::create(output)?, "{sum:.6}")?;
    Ok(())
}
