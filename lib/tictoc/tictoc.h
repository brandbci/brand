/**
 * @file
 * @author David Brandman
 * @brief Calculate time elapsed between Tic() and Toc().
 */

#include <time.h>
#include <sys/time.h>

/** Store the current system time. */
struct timespec Tic();

/** Return time elapsed since call to Tic(). */
struct timespec Toc(struct timespec *time1);

/** Print any `struct timespec` to console. */
void PrintToc(struct timespec *t);

