use risc0_zkvm::guest::env;

fn main() {
    let (operation, numbers): (u32, Vec<u64>) = env::read();
    assert!(!numbers.is_empty() && numbers.len() <= 100);
    // Include the application's 60% altered-input scenario at its maximum salary.
    assert!(numbers.iter().all(|&n| n <= 16_000_000_000));
    let result = match operation {
        1 => numbers.iter().sum(),
        2 => numbers.iter().sum::<u64>() / numbers.len() as u64,
        3 => *numbers.iter().max().unwrap(),
        4 => *numbers.iter().min().unwrap(),
        5 => {
            assert_eq!(numbers.len(), 2);
            let (salary_cents, rate_percent) = (numbers[0], numbers[1]);
            assert!(rate_percent == 10 || rate_percent == 15);
            let product = salary_cents * rate_percent;
            let (whole, remainder) = (product / 100, product % 100);
            // Match Decimal ROUND_HALF_EVEN at half-cent boundaries.
            whole + u64::from(remainder > 50 || (remainder == 50 && whole % 2 == 1))
        }
        _ => panic!("Unsupported operation"),
    };
    env::commit(&(operation, numbers, result));
}
