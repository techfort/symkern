/*
 Symkern generated backend artifact
 target: c.gaussian_array_statistics
 slice_node_ids: ['n1', 'n2']
 length: 20
 min_value: 0.0
 max_value: 20.0
 requested_statistics: ['standard_deviation', 'mean', 'median']
*/

#define _POSIX_C_SOURCE 200809L
#include <math.h>
#include <sys/stat.h>
#include <time.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DEFAULT_ARRAY_LENGTH 20
#define DEFAULT_MIN_VALUE 0.0
#define DEFAULT_MAX_VALUE 20.0
#define DEFAULT_SEED 17u
#define PI 3.14159265358979323846

static int compare_doubles(const void *left, const void *right) {
    const double a = *(const double *)left;
    const double b = *(const double *)right;
    if (a < b) {
        return -1;
    }
    if (a > b) {
        return 1;
    }
    return 0;
}

static double clamp(double value, double min_value, double max_value) {
    if (value < min_value) {
        return min_value;
    }
    if (value > max_value) {
        return max_value;
    }
    return value;
}

static uint32_t next_random(uint32_t *state) {
    *state = (*state * 1664525u) + 1013904223u;
    return *state;
}

static double next_uniform(uint32_t *state) {
    return ((double)next_random(state) + 1.0) / ((double)UINT32_MAX + 2.0);
}

static void generate_gaussian_array(double *values, size_t length, double min_value, double max_value, uint32_t seed) {
    uint32_t state = seed;
    const double midpoint = (min_value + max_value) / 2.0;
    const double sigma = (max_value - min_value) / 6.0;

    for (size_t index = 0; index < length; ++index) {
        double u1 = next_uniform(&state);
        double u2 = next_uniform(&state);
        double z0 = sqrt(-2.0 * log(u1)) * cos(2.0 * PI * u2);
        values[index] = clamp(midpoint + z0 * sigma, min_value, max_value);
    }
}

static double compute_mean(const double *values, size_t length) {
    double total = 0.0;
    for (size_t index = 0; index < length; ++index) {
        total += values[index];
    }
    return total / (double)length;
}

static double compute_population_stddev(const double *values, size_t length, double avg) {
    double squared_total = 0.0;
    for (size_t index = 0; index < length; ++index) {
        double delta = values[index] - avg;
        squared_total += delta * delta;
    }
    return sqrt(squared_total / (double)length);
}

static double compute_median(double *values, size_t length) {
    qsort(values, length, sizeof(double), compare_doubles);
    if (length % 2 == 0) {
        size_t upper = length / 2;
        size_t lower = upper - 1;
        return (values[lower] + values[upper]) / 2.0;
    }
    return values[length / 2];
}

static long long monotonic_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ((long long)ts.tv_sec * 1000000000LL) + (long long)ts.tv_nsec;
}

static int write_artifact(const char *artifact_root, const double *values, size_t length, double stddev, double avg, double med, long long generate_ns, long long stats_ns, long long persist_ns, long long total_ns) {
    char artifact_path[4096];
    snprintf(artifact_path, sizeof(artifact_path), "%s/c_artifact.json", artifact_root);

    FILE *artifact = fopen(artifact_path, "w");
    if (artifact == NULL) {
        return 1;
    }

    fprintf(artifact, "{\n  \"outputs\": {\n    \"source_array\": [");
    for (size_t index = 0; index < length; ++index) {
        fprintf(artifact, index == 0 ? "%.4f" : ", %.4f", values[index]);
    }
    fprintf(
        artifact,
        "],\n    \"statistics\": {\"standard_deviation\": %.4f, \"mean\": %.4f, \"median\": %.4f}\n  },\n  \"timings\": {\"generate_ns\": %lld, \"statistics_ns\": %lld, \"persist_ns\": %lld, \"total_ns\": %lld}\n}\n",
        stddev,
        avg,
        med,
        generate_ns,
        stats_ns,
        persist_ns,
        total_ns
    );
    fclose(artifact);
    return 0;
}

int main(int argc, char **argv) {
    int emit_json = 0;
    const char *artifact_root = NULL;
    size_t length = DEFAULT_ARRAY_LENGTH;
    double min_value = DEFAULT_MIN_VALUE;
    double max_value = DEFAULT_MAX_VALUE;
    uint32_t seed = DEFAULT_SEED;
    for (int index = 1; index < argc; ++index) {
        if (strcmp(argv[index], "--json") == 0) {
            emit_json = 1;
            continue;
        }
        if (strcmp(argv[index], "--artifact-root") == 0 && index + 1 < argc) {
            artifact_root = argv[++index];
            continue;
        }
        if (strcmp(argv[index], "--length") == 0 && index + 1 < argc) {
            length = (size_t)strtoul(argv[++index], NULL, 10);
            continue;
        }
        if (strcmp(argv[index], "--min") == 0 && index + 1 < argc) {
            min_value = strtod(argv[++index], NULL);
            continue;
        }
        if (strcmp(argv[index], "--max") == 0 && index + 1 < argc) {
            max_value = strtod(argv[++index], NULL);
            continue;
        }
        if (strcmp(argv[index], "--seed") == 0 && index + 1 < argc) {
            seed = (uint32_t)strtoul(argv[++index], NULL, 10);
            continue;
        }
        fprintf(stderr, "unknown argument: %s\n", argv[index]);
        return 2;
    }

    long long total_start_ns = monotonic_ns();
    double *values = calloc(length, sizeof(double));
    double *sorted_values = calloc(length, sizeof(double));
    if (values == NULL || sorted_values == NULL) {
        free(values);
        free(sorted_values);
        fprintf(stderr, "failed to allocate arrays\n");
        return 5;
    }

    long long generate_start_ns = monotonic_ns();
    generate_gaussian_array(values, length, min_value, max_value, seed);
    long long generate_ns = monotonic_ns() - generate_start_ns;
    memcpy(sorted_values, values, sizeof(double) * length);

    long long stats_start_ns = monotonic_ns();
    double avg = compute_mean(values, length);
    double stddev = compute_population_stddev(values, length, avg);
    double median = compute_median(sorted_values, length);
    long long stats_ns = monotonic_ns() - stats_start_ns;

    long long persist_ns = 0;
    if (artifact_root != NULL) {
        long long persist_start_ns = monotonic_ns();
        if (write_artifact(artifact_root, values, length, stddev, avg, median, generate_ns, stats_ns, 0, 0) != 0) {
            free(values);
            free(sorted_values);
            fprintf(stderr, "failed to write artifact\n");
            return 3;
        }
        persist_ns = monotonic_ns() - persist_start_ns;
    }
    long long total_ns = monotonic_ns() - total_start_ns;

    if (artifact_root != NULL) {
        if (write_artifact(artifact_root, values, length, stddev, avg, median, generate_ns, stats_ns, persist_ns, total_ns) != 0) {
            free(values);
            free(sorted_values);
            fprintf(stderr, "failed to finalize artifact\n");
            return 4;
        }
    }

    if (emit_json) {
        printf("{\"source_array\":[");
        for (size_t index = 0; index < length; ++index) {
            printf(index == 0 ? "%.4f" : ",%.4f", values[index]);
        }
        printf("],\"statistics\":{\"standard_deviation\":%.4f,\"mean\":%.4f,\"median\":%.4f},\"timings\":{\"generate_ns\":%lld,\"statistics_ns\":%lld,\"persist_ns\":%lld,\"total_ns\":%lld}}\n", stddev, avg, median, generate_ns, stats_ns, persist_ns, total_ns);
        free(values);
        free(sorted_values);
        return 0;
    }

    printf("standard_deviation=%.4f\n", stddev);
    printf("mean=%.4f\n", avg);
    printf("median=%.4f\n", median);
    free(values);
    free(sorted_values);
    return 0;
}