
#include <assert.h>
#include <stdio.h> 
#include <stdlib.h> 
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include "brand.h"

//---------------------------------------------------------------------------
//---------------------------------------------------------------------------
// Parse command line args (Redis and nickname)
//---------------------------------------------------------------------------
//---------------------------------------------------------------------------

redisContext* parse_command_line_args_init_redis(int argc, char **argv, char* NICKNAME) { 
    
    int opt;
    int redis_port;
    char redis_host[20];
    char node_stream_name[20];
    char redis_socket[40];

    int nflg = 0, sflg = 0, iflg = 0, pflg = 0, errflg = 0;

    // Parse command line args
    while ((opt = getopt(argc, argv, "n:s:i:p:")) != -1) {
        switch (opt) { 
            case 'n': 
                // missing str check on optarg
                strcpy(node_stream_name, optarg); 
                nflg++;
                break;
            case 's': 
                // missing str check on optarg
                strcpy(redis_socket, optarg); 
                sflg++;
                break;
            case 'i': 
                // missing str check on optarg
                strcpy(redis_host, optarg);
                iflg++; 
                break;
            case 'p': 
                // missing int check on optarg
                redis_port = atoi(optarg); 
                pflg++;
                break;
        }
    }

    // Must specify -n
    if (nflg == 0)
    {
        printf("[%s] ERROR: -n (nickname) argument not provided. Exiting node process.", NICKNAME);
		exit(1);
    }

    // Replace default node nickname
    printf("[%s] Process nickname changed from \"%s\" to \"%s\".\n", NICKNAME, NICKNAME, node_stream_name); 
    strcpy(NICKNAME, node_stream_name);

    redisContext *redis_context;

    if (sflg > 0)
    {
        // If -s is specified, ignore -i, and print warning if -i is also specified (that it is being ignored)
        if (iflg > 0)
        {
           printf("[%s] WARNING: Both -s (Redis socket) and -i (host IP) provided, so -i is being ignored.\n", NICKNAME); 
        }
        printf("[%s] Initializing Redis...\n", NICKNAME);
        redis_context = redisConnectUnix(redis_socket); 
        if (redis_context->err) {
            printf("[%s] Redis connection error: %s\n", NICKNAME, redis_context->errstr);
            exit(1);
        }
        printf("[%s] Redis initialized.\n", NICKNAME);
    }
    else if (iflg > 0)
    {
        // If -i is specified without -s, must also specify -p
        if (pflg == 0)
        {
           printf("[%s] ERROR: -p (port) argument not provided with -i (host IP). Exiting node process.\n", NICKNAME); 
           exit(1);
        }
        printf("[%s] Initializing Redis...\n", NICKNAME);
        redis_context = redisConnect(redis_host, redis_port); 
        if (redis_context->err) {
            printf("[%s] Redis connection error: %s\n", NICKNAME, redis_context->errstr);
            exit(1);
        }
        printf("[%s] Redis initialized.\n", NICKNAME);
    }
    // Must specify either -s or -i
    else
    {
        printf("ERROR: Neither -s (Redis socket) or -i (host IP) provided. Exiting node process.", NICKNAME); 
        exit(1);
    }

    return redis_context;
}

//---------------------------------------------------------------------------
//---------------------------------------------------------------------------
// Working with nxjson
//---------------------------------------------------------------------------
//---------------------------------------------------------------------------

// Assert that the object requested is both not NULL and has the correct type
void assert_object(const nx_json *json, nx_json_type json_type) {
    if (json == NULL) {
        printf("JSON structure returned null.\n");
        exit(1);
    } else if (json->type != json_type) {
        printf("The JSON object \"%s\" has type %d and attempted to assert it to type %d\n", json->key, json->type, json_type);
        exit(1);
    }
}

//----------------------------------------------------------------------
//----------------------------------------------------------------------

void print_type(nx_json_type json_type)
 {
    switch (json_type) {
        case NX_JSON_NULL:    printf("Type: NULL\n"); break;
        case NX_JSON_OBJECT:  printf("Type: OBJECT\n"); break;
        case NX_JSON_ARRAY:   printf("Type: ARRAY\n"); break;
        case NX_JSON_STRING:  printf("Type: STRING\n"); break;
        case NX_JSON_INTEGER: printf("Type: INTEGER\n"); break;
        case NX_JSON_DOUBLE:  printf("Type: DOUBLE\n"); break;
        case NX_JSON_BOOL:    printf("Type: BOOL\n"); break;
    }
 }

//------------------------------------------------------------------
// Read the supergraph and parse it with nx_json library
//------------------------------------------------------------------

const nx_json *get_supergraph_json(redisContext *c, redisReply *reply, char *supergraph_id) {

    char buffer[512]; 
    sprintf(buffer, "XREVRANGE supergraph_stream + %s COUNT 1", supergraph_id);

    reply = redisCommand(c, buffer);
    if (reply->type == REDIS_REPLY_ERROR) {
        printf("Error: %s\n", reply->str);
        exit(1);
    }

    // This is a valid response, and there's nothing new to see, so we return
    if (reply->type == REDIS_REPLY_NIL || reply->elements == 0)  
        return NULL;

    // Now we get the stream data in string format (should be a valid JSON, produced by supervisor.py)
    char *data = reply->element[0]->element[1]->element[1]->str;
    
    // Get the ID corresponding to the supergraph
    //strcpy(supergraph_id, reply->element[0]->element[0]->str);

    // Now we parse the data into JSON, and ensure that it's valid
    const nx_json *json = nx_json_parse_utf8(data);
    assert_object(json, NX_JSON_OBJECT);

    // free Redis reply
    freeReplyObject(reply);

    return json;

}

//----------------------------------------------------------------------
// Get the JSON object corresponding to a particular node's parameter.
//----------------------------------------------------------------------
const nx_json *get_parameter_object(const nx_json *json, const char *node, const char *parameter)
{
    // Get the JSON object of the nodes in the supergraph
    const nx_json *object_nodes = nx_json_get(json, "nodes");
    assert_object(object_nodes, NX_JSON_OBJECT);
    // Check that target node exists in the nodes object
    if(strcmp(nx_json_get(object_nodes, node)->key, node) == 0)
    {
        // Get the JSON object for the parameters within the JSON object of the node
        const nx_json *node_parameters = nx_json_get(nx_json_get(object_nodes, node), "parameters");
        //assert_object(node_parameters, NX_JSON_ARRAY);
        // Get the specific parameter from the parameters object
        const nx_json *this_parameter = nx_json_get(node_parameters, parameter);
        // Check that parameter object is not null
        if (this_parameter == NULL) {
            printf("parameter %s returned null.\n", parameter);
            exit(1);
        }
        return this_parameter;
    }
    printf("Node %s not found in the supergraph\n", node);
    exit(1);
}

//-------------------------------------------------------------------
//-- Get a parameter that is a string
//-------------------------------------------------------------------

char* get_parameter_string(const nx_json *json, const char *node, const char *parameter) 
{
    const nx_json *parameter_object = get_parameter_object(json, node, parameter);
    // Check if parameter is a string and return value
    if (parameter_object->type == NX_JSON_STRING) 
    {
        return(parameter_object->text_value);
    } 
    else 
    {
        printf("Parameter %s does not have the type string\n", parameter);
        exit(1);
    }
}

//-------------------------------------------------------------------
//-- Get a parameter INT
//-------------------------------------------------------------------
int get_parameter_int(const nx_json *json, const char *node, const char *parameter)
{
    const nx_json *parameter_object = get_parameter_object(json, node, parameter);
    // Check if parameter is an int and return value
    if (parameter_object->type == NX_JSON_INTEGER) 
    {
        return (int)parameter_object->num.u_value;
    } 
    else 
    {
        printf("Parameter %s does not have the type int\n", parameter);
        exit(1);
    }
}

//-------------------------------------------------------------------
//-- Get a parameter list int
//-------------------------------------------------------------------
int **get_parameter_list_int(const nx_json *json, const char *node, const char *parameter, int **output, int *n)
{
    const nx_json *parameter_value = get_parameter_object(json, node, parameter);
    assert_object(parameter_value, NX_JSON_ARRAY);
    *n = parameter_value->children.length;
    // printf("%s contains %d elements: ", parameter, *n);  // debug
    //allocate dynamic memory to store 2d array
    *output = (int *)malloc(sizeof(int) * (*n));
    for (int i = 0; i < *n; i++)
    {
        const nx_json *this_value = nx_json_item(parameter_value, i);
        assert_object(this_value, NX_JSON_INTEGER);
        // printf("%d ", this_value->num.u_value);  // debug
        (*output)[i] = this_value->num.u_value;
    }
    // printf("\n");  // debug
}

//-------------------------------------------------------------------
//-- Get a parameter list string
//-------------------------------------------------------------------
// TODO: The memory for output should be defined within this function, and `int n` should be `int &n`, with n
// being the number of elements to return

char*** get_parameter_list_string(const nx_json *json, const char *node, const char *parameter, char ***output, int *n)
{
    const nx_json *parameter_value = get_parameter_object(json, node, parameter);
    assert_object(parameter_value, NX_JSON_ARRAY);
    *n = parameter_value->children.length;
    // printf("%s contains %d elements: ",parameter ,*n);  // debug
    // allocate dynamic memory to store 2d array
    *output = (char **)malloc(sizeof(char *) * (*n));
    for (int i = 0; i < *n; i++) 
    {
        (*output)[i] = (char *)malloc(sizeof(char) * 512);
        const nx_json *this_value = nx_json_item(parameter_value,i);
        assert_object(this_value, NX_JSON_STRING);
        // printf("%s ", this_value->text_value);  // debug
        strcpy((*output)[i], this_value->text_value);
    }
    // printf("\n");  // debug
}

//-------------------------------------------------------------------
//-- Get graph load time 
//-------------------------------------------------------------------
unsigned long get_graph_load_ts_long(const nx_json *json)
{
    // Get the JSON object for the timestamp
    const nx_json *object_ts = nx_json_get(json, "graph_loaded_ts"); 
    if (object_ts->type == NX_JSON_INTEGER) 
    {
        return (unsigned long)object_ts->num.s_value;
    } 
    else 
    {
        printf("\"graph_loaded_ts\" does not have the type int\n");
        exit(1);
    }
}

//--------------------------------------------------------------
// Emit node state
//--------------------------------------------------------------

void emit_status(redisContext *c, const char *node_name, enum node_state state, const char *node_message) {
    
    /* XADD node_name_status * state STATE string STRING */

    char node_state[256];
    switch (state) {
        case NODE_STARTED    : sprintf(node_state, "state Initialized");    break;
        case NODE_READY      : sprintf(node_state, "state Ready");          break;
        case NODE_SHUTDOWN   : sprintf(node_state, "state Shutdown");       break;
        case NODE_FATAL_ERROR: sprintf(node_state, "state \"Fatal Error: %s\"", node_message);  break;
        case NODE_WARNING    : sprintf(node_state, "state \"Warning: %s\"",     node_message);  break;
        case NODE_INFO       : sprintf(node_state, "state \"Info: %s\"",        node_message);  break;
        default:
            printf("Unknown state %d\n", state);
            break;                     
    }
    
    char stream[512];
    redisReply *reply;
    sprintf(stream, "XADD %s_state * %s", node_name, node_state);
    printf("[%s] %s\n", node_name, stream);
    reply = redisCommand(c,stream);
    freeReplyObject(reply);
}



