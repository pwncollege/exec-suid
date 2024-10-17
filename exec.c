#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <string.h>
#include <limits.h>
#include <stdarg.h>

#define AT_EMPTY_PATH 0x1000

int log_enabled = 0;

void log_info(const char *format, ...) {
    if (log_enabled) {
        va_list args;
        va_start(args, format);
        vfprintf(stderr, format, args);
        va_end(args);
    }
}

void log_error(const char *format, ...) {
    if (log_enabled) {
        va_list args;
        va_start(args, format);
        vfprintf(stderr, format, args);
        va_end(args);
    }
    exit(1);
}

int main(int argc, char *argv[], char *envp[]) {
    log_enabled = getenv("DEBUG_EXEC") != NULL;

    char *path;
    switch (argc) {
        case 3:
            path = argv[2];
            break;
        case 2:
            path = argv[1];
            break;
        default:
            fprintf(stderr, "Usage: %s [path]\n", argv[0]);
            return 1;
    }

    int fd = open(path, O_RDONLY);
    if (fd == -1)
        log_error("Failed to open %s: %s\n", path, strerror(errno));

    char link_path[PATH_MAX];
    snprintf(link_path, sizeof(link_path), "/proc/self/fd/%d", fd);

    char link[PATH_MAX];
    ssize_t link_len = readlink(link_path, link, sizeof(link) - 1);
    if (link_len == -1)
        log_error("Failed to readlink %s: %s\n", link_path, strerror(errno));
    link[link_len] = '\0';
    log_info("Link: %s\n", link);

    char header[1024];
    FILE *file = fdopen(fd, "r");
    if (fgets(header, sizeof(header), file) == NULL)
        log_error("Failed to read header %s: %s\n", path, strerror(errno));
    log_info("Header: %s", header);

    char *header_cursor = header;
    if (strncmp(header, "#!", 2) != 0)
        log_error("File %s header does not start with #!\n", path);
    if (header[strlen(header) - 1] != '\n')
        log_error("File %s header does not end with a newline\n", path);
    header_cursor += 2;
    while ((*header_cursor == ' ' || *header_cursor == '\t') && *header_cursor != '\n')
        header_cursor++;

    char *token;
    char *exec_argv[256];
    char *script_argv[256];
    char **argv_cursor = exec_argv;
    while ((token = strsep(&header_cursor, " \t\n")) != NULL) {
        if (*token == '\0')
            continue;
        if (strcmp(token, "--") == 0)
            break;
        *argv_cursor++ = token;
    }
    *argv_cursor = NULL;
    argv_cursor = script_argv;
    while ((token = strsep(&header_cursor, " \t\n")) != NULL) {
        if (*token == '\0')
            continue;
        *argv_cursor++ = token;
    }
    *argv_cursor++ = link_path;
    *argv_cursor = NULL;

    log_info("Arguments (exec):\n");
    for (char **arg = exec_argv; *arg != NULL; arg++)
        log_info(" %s\n", *arg);
    log_info("Arguments (script):\n");
    for (char **arg = script_argv; *arg != NULL; arg++)
        log_info(" %s\n", *arg);

    if (strcmp(exec_argv[0], argv[0]) != 0)
        log_error("Executed binary %s does not match the expected binary %s\n", exec_argv[0], argv[0]);

    struct stat file_stat;
    if (fstat(fd, &file_stat) == -1)
        log_error("Failed to fstat %s: %s\n", path, strerror(errno));
    log_info("Owner (UID, GID): %d %d\n", file_stat.st_uid, file_stat.st_gid);
    log_info("Permissions: %o\n", file_stat.st_mode & 07777);

    FILE *mounts = fopen("/proc/self/mounts", "r");
    if (!mounts)
        log_error("Failed to open /proc/self/mounts: %s\n", strerror(errno));

    char *mount_lines[1024];
    int mount_lines_count = 0;
    char line[1024];
    while (fgets(line, sizeof(line), mounts)) {
        mount_lines[mount_lines_count++] = strdup(line);
        if (mount_lines_count >= 1024)
            log_error("Too many mount points to process\n");
    }
    fclose(mounts);

    char mount_point[PATH_MAX] = "";
    char mount_options[1024];
    for (int i = mount_lines_count - 1; i >= 0; i--) {
        char point[PATH_MAX];
        char options[1024];
        sscanf(mount_lines[i], "%*s %s %*s %s %*s %*s", point, options);
        if (strncmp(link, point, strlen(point)) == 0) {
            strncpy(mount_point, point, sizeof(mount_point));
            strncpy(mount_options, options, sizeof(mount_options));
            break;
        }
    }
    if (mount_point[0] == '\0')
        log_error("Failed to find mount point for %s\n", link);
    log_info("Mount Point: %s\n", mount_point);
    log_info("Mount Options: %s\n", mount_options);

    int is_nosuid = 0;
    char *mount_option = strtok(mount_options, ",");
    while (mount_option != NULL) {
        if (strcmp(mount_option, "nosuid") == 0) {
            is_nosuid = 1;
            break;
        }
        mount_option = strtok(NULL, ",");
    }

    int new_euid = file_stat.st_mode & S_ISUID && !is_nosuid ? file_stat.st_uid : getuid();
    int new_egid = file_stat.st_mode & S_ISGID && !is_nosuid ? file_stat.st_gid : getgid();

    log_info("Setting EUID to %d\n", new_euid);
    log_info("Setting EGID to %d\n", new_egid);

    if (setegid(new_egid) == -1)
        log_error("Failed to setegid %d: %s\n", new_egid, strerror(errno));

    if (seteuid(new_euid) == -1)
        log_error("Failed to seteuid %d: %s\n", new_euid, strerror(errno));

    int result = execve(script_argv[0], script_argv, envp);
    if (result == -1)
        log_error("Failed to execve %s: %s\n", path, strerror(errno));

    return 0;
}
