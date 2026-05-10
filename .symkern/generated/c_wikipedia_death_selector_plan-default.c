/*
 Symkern generated backend artifact
 target: c.wikipedia_death_selector
 slice_node_ids: ['n3']
 candidate_count_hint: 3
*/

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct {
    char candidate_id[256];
    char person[256];
    char date[64];
    int year;
    char description[512];
    char wikipedia_url[512];
    int keyword_hits;
    int description_length;
    int page_count;
    int era_bonus;
    int illustrious_score;
} Candidate;

static long long monotonic_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ((long long)ts.tv_sec * 1000000000LL) + (long long)ts.tv_nsec;
}

static int compute_score(const Candidate *candidate) {
    return (candidate->keyword_hits * 1000) + (candidate->page_count * 125) + candidate->description_length + (candidate->era_bonus * 40);
}

int main(int argc, char **argv) {
    int emit_json = 0;
    const char *input_path = NULL;
    for (int index = 1; index < argc; ++index) {
        if (strcmp(argv[index], "--json") == 0) {
            emit_json = 1;
            continue;
        }
        if (strcmp(argv[index], "--input") == 0 && index + 1 < argc) {
            input_path = argv[++index];
            continue;
        }
        fprintf(stderr, "unknown argument: %s\n", argv[index]);
        return 2;
    }
    if (input_path == NULL) {
        fprintf(stderr, "missing --input\n");
        return 3;
    }

    FILE *input = fopen(input_path, "r");
    if (input == NULL) {
        fprintf(stderr, "failed to open input\n");
        return 4;
    }

    long long total_start_ns = monotonic_ns();
    long long selection_start_ns = monotonic_ns();
    Candidate best = {0};
    int has_best = 0;
    char line[2048];
    while (fgets(line, sizeof(line), input) != NULL) {
        Candidate current = {0};
        char *cursor = line;
        char *save_ptr = NULL;
        char *fields[10] = {0};
        for (int field_index = 0; field_index < 10; ++field_index) {
            fields[field_index] = strtok_r(field_index == 0 ? cursor : NULL, "\t\n", &save_ptr);
            if (fields[field_index] == NULL) {
                fields[field_index] = "";
            }
        }
        snprintf(current.candidate_id, sizeof(current.candidate_id), "%s", fields[0]);
        snprintf(current.person, sizeof(current.person), "%s", fields[1]);
        snprintf(current.date, sizeof(current.date), "%s", fields[2]);
        current.year = atoi(fields[3]);
        snprintf(current.description, sizeof(current.description), "%s", fields[4]);
        snprintf(current.wikipedia_url, sizeof(current.wikipedia_url), "%s", fields[5]);
        current.keyword_hits = atoi(fields[6]);
        current.description_length = atoi(fields[7]);
        current.page_count = atoi(fields[8]);
        current.era_bonus = atoi(fields[9]);
        current.illustrious_score = compute_score(&current);

        if (!has_best || current.illustrious_score > best.illustrious_score) {
            best = current;
            has_best = 1;
        }
    }
    fclose(input);
    long long selection_ns = monotonic_ns() - selection_start_ns;
    long long total_ns = monotonic_ns() - total_start_ns;

    if (emit_json) {
        printf(
            "{\"selected_death\":{\"candidate_id\":\"%s\",\"person\":\"%s\",\"date\":\"%s\",\"year\":%d,\"description\":\"%s\",\"wikipedia_url\":\"%s\",\"illustrious_score\":%d},\"timings\":{\"selection_ns\":%lld,\"total_ns\":%lld}}\n",
            best.candidate_id,
            best.person,
            best.date,
            best.year,
            best.description,
            best.wikipedia_url,
            best.illustrious_score,
            selection_ns,
            total_ns
        );
        return 0;
    }

    printf("%s\n", best.person);
    return 0;
}