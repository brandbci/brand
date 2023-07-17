/* Utilities for working with BRAND in Redis */

#include  <stdbool.h>
#include  <hiredis.h>
#include  "nxjson.h"

//--------------------------------------------------------------
// Parse command line arguments and connect to Redis
//--------------------------------------------------------------

redisContext* parse_command_line_args_init_redis(int argc, char **argv, char* NICKNAME);

//--------------------------------------------------------------
// Tools for working with nxson
//--------------------------------------------------------------

const nx_json *get_supergraph_json(redisContext *c, redisReply *reply, char *supergraph_id);
char* get_parameter_string(const nx_json *json, const char *node, const char *parameter);
int get_parameter_int(const nx_json *json, const char *node, const char *parameter); 
int ** get_parameter_list_int(const nx_json *json, const char *node, const char *parameter, int **output, int *n);
char*** get_parameter_list_string(const nx_json *json, const char *node, const char *parameter, char ***output, int *n);
unsigned long get_graph_load_ts_long(const nx_json *json);
//void get_parameter_float(const nx_json *json, const char *node, const char *parameter, float *output);
//void get_parameter_bool(const nx_json *json, const char *node, const char *parameter, bool *output);

//--------------------------------------------------------------
// Emit node state
//--------------------------------------------------------------

enum node_state {NODE_STARTED, NODE_READY, NODE_SHUTDOWN, NODE_FATAL_ERROR, NODE_WARNING, NODE_SUPERGRAPH_UPDATE, NODE_INFO};
void emit_status(redisContext *c, const char *node_name, enum node_state state, const char *node_message);
