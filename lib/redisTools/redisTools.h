
#include <hiredis.h>

#define ROOT_PATH "../.."

int load_YAML_variable_string(char *process, char *yaml_path, char *value, char *buffer, int n);
int initialize_redis_from_YAML(char *process);
int load_redis_context(redisContext **redis_context, char *redis_ip, char *redis_port);

int redis_string(redisContext *redis_context, char *command, char *string, int n);
int redis_int(redisContext *redis_context, char *command, int *value);
int redis_succeed(redisContext *redis_context, char *command);





