mod pace;

fn main() {
    if let Err(error) = pace::run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
