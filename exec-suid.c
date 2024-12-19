#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>


#define HEADER_SIZE 1024

#define CHECK_ERRNO(call) ({ \
    __typeof__(call) result = (call); \
    if (result == -1) { \
        perror(#call); \
        exit(1); \
    } \
    result; \
})

int log_enabled = 0;

void log_info(const char *format, ...)
{
    if (log_enabled) {
        va_list args;
        va_start(args, format);
        vfprintf(stderr, format, args);
        va_end(args);
    }
}

void log_error(const char *format, ...)
{
    if (log_enabled) {
        va_list args;
        va_start(args, format);
        vfprintf(stderr, format, args);
        va_end(args);
    }
    exit(1);
}

void parse_shebang(int fd, char *exec_argv[], char *script_argv[])
{
    char header[HEADER_SIZE];
    FILE *file = fdopen(fd, "r");
    if (fgets(header, HEADER_SIZE, file) == NULL)
        log_error("Failed to read header: %s\n", strerror(errno));
    log_info("Header: %s", header);

    char *header_cursor = header;
    if (strncmp(header, "#!", 2) != 0)
        log_error("Header does not start with #!\n");
    if (header[strlen(header) - 1] != '\n')
        log_error("Header does not end with a newline\n");
    header_cursor += 2;
    while ((*header_cursor == ' ' || *header_cursor == '\t') && *header_cursor != '\n')
        header_cursor++;

    char *token;
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
    *argv_cursor = NULL;
}

bool check_path_in_nosuid_mount(char *path)
{
    FILE *mounts = fopen("/proc/self/mounts", "r");
    if (!mounts)
        log_error("  Failed to open /proc/self/mounts: %s\n", strerror(errno));

    char *mount_lines[1024];
    int mount_lines_count = 0;
    char line[1024];
    while (fgets(line, sizeof(line), mounts)) {
        mount_lines[mount_lines_count++] = strdup(line);
        if (mount_lines_count >= 1024)
            log_error("  Too many mount points to process\n");
    }
    fclose(mounts);

    char mount_point[PATH_MAX] = "";
    char mount_options[1024];
    for (int i = mount_lines_count - 1; i >= 0; i--) {
        char point[PATH_MAX];
        char options[1024];
        sscanf(mount_lines[i], "%*s %s %*s %s %*s %*s", point, options);
        if (strncmp(path, point, strlen(point)) == 0) {
            strncpy(mount_point, point, sizeof(mount_point));
            strncpy(mount_options, options, sizeof(mount_options));
            break;
        }
    }
    if (mount_point[0] == '\0')
        log_error("  Failed to find mount point for %s\n", path);

    log_info("  Mount Point: %s\n", mount_point);
    log_info("  Mount Options: %s\n", mount_options);

    char *mount_option = strtok(mount_options, ",");
    while (mount_option != NULL) {
        if (strcmp(mount_option, "nosuid") == 0) {
            return true;
        }
        mount_option = strtok(NULL, ",");
    }

    return false;
}

int validate_secure_path(char *path)
{
    char path_copy[PATH_MAX];
    strncpy(path_copy, path, sizeof(path_copy));
    int fd = path_copy[0] == '/' ? CHECK_ERRNO(open("/", O_RDONLY|O_CLOEXEC)) : AT_FDCWD;
    char *path_part = strtok(path_copy, "/");
    log_info("Checking if path is secure: ");
    while (path_part != NULL) {
        if (fd != AT_FDCWD) {
            log_info("/");
        }
        log_info("%s", path_part);
        int new_fd = openat(fd, path_part, O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
        if (new_fd == -1) {
            if (errno == ENOENT) {
                log_error("\n Insecure: path does not exist\n");
            } else if (errno == ELOOP) {
                log_error("\n Insecure: path is a symlink\n");
            } else {
                log_error("\n %s\n", strerror(errno));
            }
        }
        struct stat stat;
        CHECK_ERRNO(fstat(new_fd, &stat));
        if (stat.st_uid != 0) {
            log_error("\n Insecure: path is not owned by root");
        }
        if (fd != AT_FDCWD) {
            close(fd);
        }
        fd = new_fd;
        path_part = strtok(NULL, "/");
    }
    log_info("\n");

    char fd_path[PATH_MAX];
    snprintf(fd_path, sizeof(fd_path), "/proc/self/fd/%d", fd);
    ssize_t link_len = CHECK_ERRNO(readlink(fd_path, path_copy, sizeof(path_copy) - 1));
    path_copy[link_len] = '\0';
    log_info(" Checking if path is in nosuid mount\n");
    if (check_path_in_nosuid_mount(path_copy)) {
        log_error("  Insecure: path is in a nosuid mount\n");
    }

    log_info(" Path is secure\n");
    return fd;
}


int main(int argc, char *argv[], char *envp[])
{
    log_enabled = getenv("DEBUG_EXEC_SUID") != NULL;

    if (argc <= 1) {
        fprintf(stderr, "Usage: %s [path]\n", argv[0]);
        return 1;
    }

    char *path = argv[argc == 2 ? 1 : 2];
    log_info("Path: %s\n", path);

    int fd = validate_secure_path(path);

    char *exec_argv[256];
    char *script_argv[256];
    parse_shebang(fd, exec_argv, script_argv);

    char **script_arg;
    for (script_arg = script_argv; *script_arg != NULL; script_arg++);
    *script_arg++ = path;
    for (char **arg = &argv[(argc == 2 ? 1 : 2) + 1]; *arg != NULL; arg++)
        *script_arg++ = *arg;
    *script_arg = NULL;

    log_info("Arguments (exec):\n");
    for (char **arg = exec_argv; *arg != NULL; arg++)
        log_info(" %s\n", *arg);
    log_info("Arguments (script):\n");
    for (char **arg = script_argv; *arg != NULL; arg++)
        log_info(" %s\n", *arg);

    if (strcmp(exec_argv[0], argv[0]) != 0)
        log_error("Executed binary %s does not match the expected binary %s\n", exec_argv[0], argv[0]);

    uid_t uid = getuid();
    gid_t gid = getgid();

    struct stat stat;
    CHECK_ERRNO(fstat(fd, &stat));
    log_info("Owner (UID, GID): %d %d\n", stat.st_uid, stat.st_gid);
    log_info("Permissions: %o\n", stat.st_mode & 07777);
    int setuid = stat.st_mode & S_ISUID;
    int setgid = stat.st_mode & S_ISGID;

    int new_euid = setuid ? stat.st_uid : uid;
    int new_egid = setgid ? stat.st_gid : gid;
    log_info("Setting EUID to %d\n", new_euid);
    log_info("Setting EGID to %d\n", new_egid);
    CHECK_ERRNO(setegid(new_egid));
    CHECK_ERRNO(seteuid(new_euid));

    CHECK_ERRNO(execve(script_argv[0], script_argv, NULL));

    return 0;
}
