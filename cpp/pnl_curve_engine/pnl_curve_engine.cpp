#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Bucket {
    std::string name;
    double price;
    double shares;
    double model_probability;
};

std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> parts;
    std::stringstream stream(line);
    std::string item;
    while (std::getline(stream, item, ',')) {
        parts.push_back(item);
    }
    return parts;
}

double parse_double(const std::string& value, const std::string& field) {
    char* end = nullptr;
    const double parsed = std::strtod(value.c_str(), &end);
    if (end == value.c_str() || *end != '\0') {
        throw std::runtime_error("invalid numeric field " + field + ": " + value);
    }
    return parsed;
}

void validate_bucket(const Bucket& bucket) {
    if (bucket.name.empty()) {
        throw std::runtime_error("bucket name is required");
    }
    if (bucket.price < 0.0 || bucket.price > 1.0) {
        throw std::runtime_error(bucket.name + ": price must be between 0 and 1");
    }
    if (bucket.shares < 0.0) {
        throw std::runtime_error(bucket.name + ": shares must not be negative");
    }
    if (bucket.model_probability < 0.0 || bucket.model_probability > 1.0) {
        throw std::runtime_error(bucket.name + ": model_probability must be between 0 and 1");
    }
}

std::vector<Bucket> read_buckets(const std::string& path) {
    std::ifstream file(path);
    if (!file) {
        throw std::runtime_error("could not open input file: " + path);
    }

    std::vector<Bucket> buckets;
    std::string line;
    bool first_line = true;
    while (std::getline(file, line)) {
        if (line.empty()) {
            continue;
        }
        if (first_line) {
            first_line = false;
            if (line == "bucket,price,shares,model_probability") {
                continue;
            }
        }

        const std::vector<std::string> parts = split_csv_line(line);
        if (parts.size() != 4) {
            throw std::runtime_error("expected 4 CSV fields: " + line);
        }

        Bucket bucket{
            parts[0],
            parse_double(parts[1], "price"),
            parse_double(parts[2], "shares"),
            parse_double(parts[3], "model_probability"),
        };
        validate_bucket(bucket);
        buckets.push_back(bucket);
    }

    if (buckets.empty()) {
        throw std::runtime_error("at least one bucket is required");
    }
    return buckets;
}

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: pnl_curve_engine <bucket_csv>\n";
        return 2;
    }

    try {
        const std::vector<Bucket> buckets = read_buckets(argv[1]);
        double total_cost = 0.0;
        for (const Bucket& bucket : buckets) {
            total_cost += bucket.price * bucket.shares;
        }

        std::cout << "bucket,price,shares,cost,model_probability,edge,pnl_if_wins\n";
        std::cout << std::fixed << std::setprecision(6);
        for (const Bucket& bucket : buckets) {
            const double cost = bucket.price * bucket.shares;
            const double edge = bucket.model_probability - bucket.price;
            const double pnl_if_wins = bucket.shares - total_cost;
            std::cout << bucket.name << ","
                      << bucket.price << ","
                      << bucket.shares << ","
                      << cost << ","
                      << bucket.model_probability << ","
                      << edge << ","
                      << pnl_if_wins << "\n";
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << "\n";
        return 1;
    }

    return 0;
}
